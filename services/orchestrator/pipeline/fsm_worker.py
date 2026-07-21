"""
pipeline/fsm_worker.py — Finite State Machine orchestrating conversation turns.

The FSMWorker is the brain of the pipeline. It receives transcripts from
STTWorker and sentences/responses back from LLMWorker, then decides what to
do: route to TTS, handle interruptions, commit history, etc.

Message routing (all via a single internal funnel queue for serial ordering):
  transcript_input   → _handle_transcript   (new user utterance)
  llm_output         → _handle_llm_sentence / _handle_llm_response
  cancel_input       → _handle_cancel       (stop / barge-in command)
  word_input         → _handle_word         (TTS word progress tracking)
  playback_done_input→ _handle_playback_done (turn completion signal)

Idempotency guarantees:
  • _pending_responses[turn_key]["status"] transitions: pending → completed
    OR pending → cancelled OR pending → interrupted. Only one transition is
    allowed per turn, enforced by status checks before writing history.
  • Cancellation resets (cancel token + cancellation_manager reset) happen one
    event-loop tick after the interruption signal so in-flight executor threads
    for the old turn see is_cancelled=True before we clear it for the new turn.

Telemetry emitted (consistent across normal, interrupt, cancel, error paths):
  • llm_request      — every new user turn
  • cancellation     — every cancel / barge-in
  • interruption_decision_logged — when interruption intelligence runs
  • fsm_* logger events (not telemetry_bus) for internal diagnostics
  • error            — on unexpected exception
"""

import asyncio
from common.config.voice_settings import get as vc_get
from common.logging.logger import get_logger
from services.edge_auth.telemetry_bus import telemetry_bus
from .base import PipelineStage
from .messages import (
    TranscriptMessage, LLMRequest, LLMResponse, LLMSentenceChunk,
    TTSRequest, TextResponse, CancelCommand, MetricsEvent,
    WordMessage, PlaybackDoneMessage,
)
from .cancel_token import (
    get_cancel_token, reset_cancel_token, get_current_turn, set_current_turn,
)

logger = get_logger("async-pipeline")


class _SessionState:
    __slots__ = ("turn_id", "current_reply", "resume_text", "spoken_words", "interrupted")

    def __init__(self):
        self.turn_id: int = 0
        self.current_reply: str = ""
        self.resume_text: str = ""
        self.spoken_words: list[str] = []
        self.interrupted: bool = False


class FSMWorker(PipelineStage):
    def __init__(self):
        super().__init__("fsm")
        self.transcript_input: asyncio.Queue = asyncio.Queue()
        self.llm_input: asyncio.Queue = asyncio.Queue()
        self.llm_output: asyncio.Queue = asyncio.Queue()
        self.tts_input: asyncio.Queue = asyncio.Queue()
        self.cancel_input: asyncio.Queue = asyncio.Queue()
        self.metrics_output: asyncio.Queue = asyncio.Queue()
        self.word_input: asyncio.Queue = asyncio.Queue()
        self.playback_done_input: asyncio.Queue = asyncio.Queue()
        self.playback_input: asyncio.Queue | None = None
        self.playback = None  # Set by VoicePipeline after wiring
        self._sessions: dict[str, _SessionState] = {}
        self._pending_responses: dict[tuple[str, int], dict] = {}

    # ------------------------------------------------------------------ #
    # Internal funnel: serialise all input queues into one                 #
    # ------------------------------------------------------------------ #

    async def _queue_consumer(self, q: asyncio.Queue, kind: str):
        while not self._cancel_event.is_set():
            try:
                item = await q.get()
                await self._funnel.put((kind, item))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.log(
                    "fsm_consumer_error", "system", "system",
                    detail={"error": str(e), "kind": kind},
                )
                err_msg = str(e).lower()
                if isinstance(e, RuntimeError) and (
                    "different event loop" in err_msg or "loop is closed" in err_msg
                ):
                    break
                await asyncio.sleep(0.1)

    async def run(self):
        self._funnel: asyncio.Queue = asyncio.Queue()
        consumers = [
            asyncio.create_task(
                self._queue_consumer(self.transcript_input, "transcript")
            ),
            asyncio.create_task(
                self._queue_consumer(self.llm_output, "llm_response")
            ),
            asyncio.create_task(
                self._queue_consumer(self.cancel_input, "cancel")
            ),
            asyncio.create_task(
                self._queue_consumer(self.word_input, "word")
            ),
            asyncio.create_task(
                self._queue_consumer(self.playback_done_input, "playback_done")
            ),
        ]
        try:
            while not self._cancel_event.is_set():
                try:
                    kind, msg = await asyncio.wait_for(
                        self._funnel.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    continue

                if self._cancel_event.is_set():
                    break

                try:
                    if kind == "transcript":
                        await self._handle_transcript(msg)
                    elif kind == "llm_response":
                        await self._handle_llm_response(msg)
                    elif kind == "cancel":
                        await self._handle_cancel(msg)
                    elif kind == "word":
                        await self._handle_word(msg)
                    elif kind == "playback_done":
                        await self._handle_playback_done(msg)
                except Exception as e:
                    sid = getattr(msg, "session_id", "system")
                    tid = str(getattr(msg, "turn_id", "?"))
                    logger.log("fsm_error", sid, tid, detail={"error": str(e)})
                    telemetry_bus.push(
                        "error",
                        {"message": f"FSM Stage Error: {e}"},
                        sid, tid,
                    )
        finally:
            for c in consumers:
                if not c.done():
                    c.cancel()
            await asyncio.gather(*consumers, return_exceptions=True)

    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #

    async def _handle_transcript(self, msg: TranscriptMessage):
        logger.log(
            "fsm_transcript_received", msg.session_id,
            str(getattr(msg, "turn_id", "0")),
            detail={"text": msg.text[:80]},
        )

        # Discard if client already disconnected
        if self.playback and msg.session_id not in self.playback._clients:
            logger.log(
                "fsm_discard_disconnected_session", msg.session_id,
                str(msg.turn_id),
                detail={"msg": "Discarding transcript: client already disconnected"},
            )
            return

        state = self._get_session(msg.session_id)

        # Evict / mark interrupted any stray pending entry from the previous turn
        prev_turn_key = (msg.session_id, state.turn_id)
        if prev_turn_key in self._pending_responses:
            entry = self._pending_responses[prev_turn_key]
            if entry["status"] == "pending":
                entry["status"] = "interrupted"
                spoken = self._compute_spoken(state, entry["text"])
                if spoken:
                    from services.orchestrator.state_store import save_turn
                    save_turn(
                        msg.session_id, str(state.turn_id),
                        "assistant", " ".join(spoken),
                    )
            # Evict all completed/cancelled entries for this session
            keys_to_del = [
                k for k in self._pending_responses
                if k[0] == msg.session_id and k[1] <= state.turn_id
            ]
            for k in keys_to_del:
                self._pending_responses.pop(k, None)

        state.turn_id += 1
        set_current_turn(msg.session_id, state.turn_id)
        turn_str = str(state.turn_id)

        # Interruption classification
        is_interrupted = state.interrupted
        state.interrupted = False

        if is_interrupted:
            from services.orchestrator.interruption_intelligence import interruption_intel
            intel_res = interruption_intel.evaluate_interruption(
                transcript=msg.text,
                stt_confidence=1.0,
                speech_duration_ms=vc_get("interruption.min_speech_duration_ms", 300),
                assistant_speaking_time_ms=1000,
                fsm_state="speaking",
                is_final=True,
                context={"session_id": msg.session_id, "turn_id": msg.turn_id},
            )
            decision = intel_res["decision"]
            category = intel_res["category"]

            logger.log(
                event_name="interruption_decision_logged",
                session_id=msg.session_id,
                turn_id=turn_str,
                detail={
                    "transcript": msg.text,
                    "category": category,
                    "decision": decision,
                    "reason": intel_res.get("reason", ""),
                },
            )

            spoken = self._compute_spoken(state, state.current_reply)
            unspoken = state.current_reply.split()[len(spoken):]

            from services.orchestrator.context_merge import resolve
            res = resolve(msg.session_id, spoken, unspoken, category)
            if res["strategy"] == "clarification":
                state.resume_text = " ".join(unspoken)

            from services.orchestrator.tools import tool_manager
            tool_manager.on_interruption_during_call(msg.session_id, category)

            state.spoken_words = []

            if decision in ("ABORT_ALL", "IGNORE_CONTINUE"):
                return

        # Reset spoken state for the new turn
        state.spoken_words = []
        if self.playback:
            self.playback.reset_spoken_duration(msg.session_id)
        state.current_reply = ""

        # BUG FIX: yield one tick so in-flight executor threads for the old
        # turn see is_cancelled=True before we clear it.
        await asyncio.sleep(0)
        reset_cancel_token(msg.session_id)
        from services.orchestrator.cancellation_manager import cancellation_manager
        cancellation_manager.reset_session(msg.session_id)

        from services.orchestrator.state_store import load_history, save_turn
        history = load_history(msg.session_id)

        if state.resume_text:
            history.append({
                "role": "system",
                "content": (
                    "Note: The user interrupted your previous response. "
                    "After addressing the user's latest query, please resume/"
                    "incorporate the following unspoken points: "
                    + state.resume_text
                ),
            })
            state.resume_text = ""

        history.append({"role": "user", "content": msg.text})
        save_turn(msg.session_id, turn_str, "user", msg.text)

        telemetry_bus.push(
            "llm_request", {"text": msg.text[:80]}, msg.session_id, turn_str
        )
        logger.log("fsm_llm_request_sent", msg.session_id, turn_str, detail={})

        from common.config.runtime_limits import get_limits
        limits = get_limits()
        user_text_lower = msg.text.lower()
        detail_keywords = [
            "detailed", "detail", "explain in depth", "tell me more",
            "explain more", "thorough", "elaborate", "explain", "describe",
            "how does", "why is", "compare", "what is the difference",
            "tell me about", "in depth", "walk me through", "how do i",
            "can you explain",
        ]
        is_detail_requested = any(kw in user_text_lower for kw in detail_keywords)

        if is_detail_requested:
            max_tokens_override = limits["detail_max_tokens"]
            max_sentences_override = limits["detail_max_sentences"]
            logger.log(
                "fsm_detailed_mode_triggered", msg.session_id, turn_str,
                detail={
                    "max_tokens": max_tokens_override,
                    "max_sentences": max_sentences_override,
                },
            )
        else:
            max_tokens_override = limits["normal_max_tokens"]
            max_sentences_override = limits["normal_max_sentences"]

        await self.llm_input.put(
            LLMRequest(
                messages=history,
                session_id=msg.session_id,
                turn_id=state.turn_id,
                max_tokens=max_tokens_override,
                max_sentences=max_sentences_override,
            )
        )

    async def _handle_llm_response(self, msg):
        if isinstance(msg, LLMSentenceChunk):
            await self._handle_llm_sentence(msg)
        else:
            # Legacy single-shot path (test injection)
            logger.log(
                "fsm_llm_response_received", msg.session_id, str(msg.turn_id),
                detail={"text": msg.text[:60]},
            )
            state = self._get_session(msg.session_id)
            state.current_reply = msg.text
            self._pending_responses[(msg.session_id, msg.turn_id)] = {
                "text": msg.text, "status": "pending"
            }
            logger.log(
                "fsm_sending_to_tts", msg.session_id, str(msg.turn_id),
                detail={},
            )
            await self.tts_input.put(
                TTSRequest(
                    text=msg.text,
                    session_id=msg.session_id,
                    turn_id=msg.turn_id,
                    is_final_sentence=True,
                )
            )
            if self.playback_input:
                await self.playback_input.put(
                    TextResponse(
                        text=msg.text,
                        session_id=msg.session_id,
                        turn_id=msg.turn_id,
                        tokens=msg.tokens,
                        latency_ms=msg.latency_ms,
                    )
                )
            await self.metrics_output.put(
                MetricsEvent(
                    "turn_complete", msg.session_id, str(msg.turn_id),
                    {"reply": msg.text[:60], "tokens": msg.tokens},
                )
            )

    async def _handle_llm_sentence(self, msg: LLMSentenceChunk):
        state = self._get_session(msg.session_id)
        sep = " " if state.current_reply else ""
        state.current_reply += sep + msg.text
        turn_key = (msg.session_id, msg.turn_id)

        # Upsert pending entry with latest text so _handle_cancel always has
        # the most recently dispatched text even if interrupted pre-is_final.
        if turn_key not in self._pending_responses:
            self._pending_responses[turn_key] = {
                "text": state.current_reply, "status": "pending"
            }
        elif self._pending_responses[turn_key]["status"] == "pending":
            self._pending_responses[turn_key]["text"] = state.current_reply

        if msg.text or msg.is_final:
            logger.log(
                "fsm_sending_to_tts", msg.session_id, str(msg.turn_id),
                detail={
                    "sentence_idx": msg.sentence_index,
                    "is_final": msg.is_final,
                },
            )
            await self.tts_input.put(
                TTSRequest(
                    text=msg.text,
                    session_id=msg.session_id,
                    turn_id=msg.turn_id,
                    is_final_sentence=msg.is_final,
                )
            )

        if msg.is_final:
            full_text = msg.full_reply_text or state.current_reply
            if self._pending_responses[turn_key]["status"] == "pending":
                self._pending_responses[turn_key]["text"] = full_text

            if self.playback_input:
                await self.playback_input.put(
                    TextResponse(
                        text=full_text,
                        session_id=msg.session_id,
                        turn_id=msg.turn_id,
                        tokens=msg.tokens,
                        latency_ms=msg.latency_ms,
                    )
                )
            logger.log(
                "fsm_llm_sentences_complete", msg.session_id, str(msg.turn_id),
                detail={"sentences": msg.sentence_index + 1, "tokens": msg.tokens},
            )
            await self.metrics_output.put(
                MetricsEvent(
                    "turn_complete", msg.session_id, str(msg.turn_id),
                    {"reply": full_text[:60], "tokens": msg.tokens},
                )
            )

    async def _handle_cancel(self, msg: CancelCommand):
        tok = get_cancel_token(msg.session_id)
        tok.cancel(msg.reason)
        from services.orchestrator.cancellation_manager import cancellation_manager
        cancellation_manager.cancel_session(msg.session_id, msg.reason)

        telemetry_bus.push(
            "cancellation", {"reason": msg.reason}, msg.session_id, "system"
        )
        await self.metrics_output.put(
            MetricsEvent(
                "cancellation", msg.session_id, "system", {"reason": msg.reason}
            )
        )

        state = self._get_session(msg.session_id)
        state.interrupted = True

        norm_reason = msg.reason.lower().replace("-", "_")
        interruption_type = (
            norm_reason
            if norm_reason in (
                "correction", "topic_change", "clarification", "stop_cancel", "add_on"
            )
            else "stop_cancel"
        )

        # IDEMPOTENCY: only cancel once per pending turn
        turn_key = (msg.session_id, state.turn_id)
        if turn_key in self._pending_responses:
            entry = self._pending_responses[turn_key]
            if entry["status"] == "pending":
                entry["status"] = "cancelled"
                spoken = self._compute_spoken(state, entry["text"])
                if spoken:
                    from services.orchestrator.state_store import save_turn
                    save_turn(
                        msg.session_id, str(state.turn_id),
                        "assistant", " ".join(spoken),
                    )

        from services.orchestrator.tools import tool_manager
        tool_manager.on_interruption_during_call(msg.session_id, interruption_type)

    async def _handle_playback_done(self, msg: PlaybackDoneMessage):
        # IDEMPOTENCY: commit only once — prevent double-write if cancel
        # and playback_done arrive close together.
        turn_key = (msg.session_id, msg.turn_id)
        if turn_key in self._pending_responses:
            entry = self._pending_responses[turn_key]
            if entry["status"] == "pending":
                entry["status"] = "completed"
                from services.orchestrator.state_store import save_turn
                save_turn(
                    msg.session_id, str(msg.turn_id), "assistant", entry["text"]
                )

    async def _handle_word(self, msg: WordMessage):
        state = self._get_session(msg.session_id)
        state.spoken_words.append(msg.word)

    # ------------------------------------------------------------------ #
    # Session helpers                                                       #
    # ------------------------------------------------------------------ #

    def _get_session(self, session_id: str) -> _SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionState()
        return self._sessions[session_id]

    def get_session_turn_id(self, session_id: str) -> int:
        state = self._sessions.get(session_id)
        return state.turn_id if state else 0

    def cleanup_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        stale_keys = [
            k for k in list(self._pending_responses)
            if k[0] == session_id
            and self._pending_responses[k]["status"] != "pending"
        ]
        for k in stale_keys:
            self._pending_responses.pop(k, None)

    def _compute_spoken(
        self, state: _SessionState, full_text: str
    ) -> list[str]:
        """Return the list of words that were actually spoken, using word
        tracking if available, otherwise falling back to timing estimation."""
        spoken = list(getattr(state, "spoken_words", []))
        full_reply_words = full_text.split()
        if not spoken:
            spoken_duration = (
                self.playback.get_spoken_duration(
                    # we need session_id — caller must handle
                    ""
                )
                if self.playback
                else 0.0
            )
            words_spoken_count = max(
                1 if spoken_duration > 0.0 else 0,
                int(spoken_duration * 2.3),
            )
            words_spoken_count = min(words_spoken_count, len(full_reply_words))
            return full_reply_words[:words_spoken_count]
        num_spoken = min(len(spoken), len(full_reply_words))
        return full_reply_words[:num_spoken]
