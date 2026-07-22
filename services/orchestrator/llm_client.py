import time
from typing import Optional
from common.config.settings import get_settings
from common.config.voice_settings import get as vc_get
from common.logging.logger import get_logger
from services.edge_auth.telemetry_bus import telemetry_bus
from services.orchestrator.context_manager import (
    estimate_tokens,
    get_token_budget,
    prepare_context,
)

logger = get_logger("primary-llm")

def call_primary_direct(session_id: str, turn_id: str, messages: list[dict]) -> str:
    """Streams completions from Groq or mock fallback depending on configuration."""
    settings = get_settings()
    api_key = settings.groq_api_key
    
    start_time = time.time()
    
    # Return context-aware response if using dummy keys or test mode
    if not api_key or api_key == "dummy_val" or settings.env == "test":
        time.sleep(vc_get("llm.mock_sleep_ms", 50) / 1000.0)
        latency_ms = int((time.time() - start_time) * 1000)
        logger.log(
            event_name="llm_first_token",
            session_id=session_id,
            turn_id=turn_id,
            latency_ms=latency_ms,
            detail={}
        )
        logger.log(
            event_name="llm_complete",
            session_id=session_id,
            turn_id=turn_id,
            latency_ms=latency_ms + 10,
            detail={"provider": "groq_mock"}
        )
        last_user_message = messages[-1]["content"].lower() if messages else ""
        if "mars" in last_user_message:
            return "Mars is the fourth planet from the Sun. It is the second-smallest planet in the Solar System."
        elif "far" in last_user_message or "distance" in last_user_message:
            context_has_mars = any("mars" in msg["content"].lower() for msg in messages[:-1])
            if context_has_mars:
                return "It is about 225 million kilometers away from Earth on average."
            else:
                return "Distance to what? Please specify the object."
        else:
            return "You're welcome!"

    # Apply context management (dedup, compress, sliding window, summarization, budget)
    budget = get_token_budget(session_id)
    context_history = prepare_context(messages, session_id)
    system_prompt = vc_get("llm.system_prompt", "You are a helpful, concise voice assistant.")
    payload = [
        {"role": "system", "content": system_prompt}
    ] + context_history

    prompt_tokens = estimate_tokens(system_prompt) + sum(estimate_tokens(m.get("content", "")) for m in context_history)
    budget.record_prompt(prompt_tokens)

    from groq import Groq
    client = Groq(api_key=api_key)
    
    chat_completion = client.chat.completions.create(
        messages=payload,
        model=settings.groq_model,
        stream=True
    )
    
    from services.orchestrator.cancellation_manager import cancellation_manager
    
    collected_chunks = []
    first_token_fired = False
    for chunk in chat_completion:
        # Check if cancelled mid-turn to abort token generation immediately
        if cancellation_manager.is_cancelled(session_id):
            logger.log(
                event_name="llm_cancelled",
                session_id=session_id,
                turn_id=turn_id,
                detail={"msg": "LLM token stream aborted mid-turn."}
            )
            return ""
            
        delta = chunk.choices[0].delta.content or ""
        collected_chunks.append(delta)
        if delta and not first_token_fired:
            first_token_fired = True
            latency_ms = int((time.time() - start_time) * 1000)
            logger.log(
                event_name="llm_first_token",
                session_id=session_id,
                turn_id=turn_id,
                latency_ms=latency_ms,
                detail={}
            )
            
    full_text = "".join(collected_chunks)
    total_latency_ms = int((time.time() - start_time) * 1000)
    completion_tok = estimate_tokens(full_text)
    budget = get_token_budget(session_id)
    budget.record_completion(completion_tok)
    logger.log(
        event_name="llm_complete",
        session_id=session_id,
        turn_id=turn_id,
        latency_ms=total_latency_ms,
        detail={"provider": "groq", "prompt_tokens": budget.prompt_tokens,
                "completion_tokens": completion_tok, "budget_pct": budget.usage_pct}
    )
    return full_text

def call_primary(session_id: str, turn_id: str, messages: list[dict]) -> str:
    """
    Outer LLM client wrapper that checks semantic cache first,
    then executes call_with_failover and caches the response.
    """
    from services.orchestrator import cache_client, failover
    settings = get_settings()
    
    # Extract query
    query = messages[-1]["content"] if messages else ""
    system_prompt = vc_get("llm.system_prompt", "You are a helpful, concise voice assistant.")
    model_name = settings.groq_model or "groq-default"
    
    # 1. Semantic Cache Lookup
    cached_res = cache_client.lookup(session_id, turn_id, query, system_prompt, model_name, messages)
    if cached_res is not None:
        return cached_res
        
    # 2. Call Failover Router
    response = failover.call_with_failover(session_id, turn_id, messages)
    
    # 3. Store in Semantic Cache
    cache_client.store(session_id, query, response, system_prompt, model_name, messages)
    
    return response


_SENTENCE_END_RE = None  # compiled lazily once at module level


def _get_sentence_re():
    """Return the compiled sentence-boundary regex, building it on first call.

    Split points (in priority order):
      • Period/exclamation/question mark followed by whitespace (excluding common
        abbreviations via negative lookbehind).
      • Semicolon followed by whitespace — clause-level boundary.
      • Comma followed by whitespace — allows TTS to begin streaming mid-sentence,
        dramatically reducing Time-To-First-Audio (TTFA) for long opening clauses.
    """
    import re
    global _SENTENCE_END_RE
    if _SENTENCE_END_RE is None:
        # 1. Sentence-ending punctuation (. ! ? \n) with abbreviation exclusion.
        abbrev_lookbehind = (
            r'(?<!\bMr)(?<!\bDr)(?<!\betc)(?<!\bvs)(?<!\be\.g)(?<!\bi\.e)'
        )
        sentence_end = rf'(?:(?<=[!?\n])|(?<={abbrev_lookbehind}\.))\s+'
        # 2. Semicolons — strong clause boundary, split aggressively.
        semicolon = r'(?<=;)\s+'
        # 3. Commas — weaker boundary; only split when followed by a space so
        #    we don't break on decimal numbers (1,234) or quoted lists.
        comma = r'(?<=,)\s+(?=[A-Za-z])'
        pattern = rf'(?:{sentence_end}|{semicolon}|{comma})'
        _SENTENCE_END_RE = re.compile(pattern, re.IGNORECASE)
    return _SENTENCE_END_RE


def select_model(query: str, requested_model: Optional[str] = None) -> str:
    """Routes short/simple conversational queries to fast model or respects requested model from UI/settings."""
    settings = get_settings()
    if requested_model:
        return requested_model
    if settings.openai_model and settings.openai_model != "openai/gpt-oss-20b":
        return settings.openai_model
    words = query.strip().lower().split()
    if len(words) <= 8 or any(w in query.lower() for w in ["hello", "hi", "hey", "who are you", "how are you"]):
        return vc_get("llm.fast_model", "llama-3.1-8b-instant")
    return settings.groq_model or "llama-3.3-70b-versatile"


def call_primary_streaming(
    session_id: str,
    turn_id: str,
    messages: list[dict],
    sentence_callback,
    max_tokens: int | None = None,
    system_prompt: str | None = None,
) -> str:
    """
    Stream LLM tokens from Groq and call sentence_callback(text: str) at each
    sentence boundary.  Returns the full accumulated text.

    Boundary rule: split on '.', '!', '?' or newline followed by whitespace.
    Abbreviations/decimals that contain '.' are treated as boundaries — this is
    an explicit design decision; full NLP tokenisation is out of scope.

    Special paths (no live streaming):
    - Cache hit  : sentence_callback called once with full cached text.
    - Mock / test: sentence_callback called once with mock text.
    - OpenAI fallback (circuit breaker open or Groq error): sentence_callback
      called once with the full buffered reply.
    """
    from services.orchestrator import cache_client, failover
    from services.orchestrator.cancellation_manager import cancellation_manager

    settings = get_settings()
    query = messages[-1]["content"] if messages else ""
    if system_prompt is None:
        system_prompt = vc_get("llm.system_prompt", "You are a helpful, concise voice assistant.")
    model_name = settings.groq_model or "groq-default"

    # ------------------------------------------------------------------ #
    # 1. Semantic cache hit — emit as a single sentence, skip generation   #
    # ------------------------------------------------------------------ #
    cached = cache_client.lookup(session_id, turn_id, query, system_prompt, model_name, messages)
    if cached is not None:
        if cached and not cancellation_manager.is_cancelled(session_id):
            telemetry_bus.push("llm_first_token", {"latency_ms": 0, "provider": "cache"}, session_id, turn_id)
            sentence_callback(cached)
            telemetry_bus.push("llm_complete", {"latency_ms": 0, "provider": "cache"}, session_id, turn_id)
        return cached

    api_key = settings.groq_api_key

    # ------------------------------------------------------------------ #
    # 2. Mock / test path                                                  #
    # ------------------------------------------------------------------ #
    if not api_key or api_key == "dummy_val" or settings.env == "test":
        start_time = time.time()
        full_text = call_primary_direct(session_id, turn_id, messages)
        latency_ms = int((time.time() - start_time) * 1000)
        telemetry_bus.push("llm_first_token", {"latency_ms": latency_ms}, session_id, turn_id)
        from services.orchestrator.async_pipeline import get_current_turn
        if full_text:
            sentence_re = _get_sentence_re()
            sentences = [s.strip() for s in sentence_re.split(full_text) if s.strip()]
            for idx, sentence in enumerate(sentences):
                if cancellation_manager.is_cancelled(session_id) or int(turn_id) < get_current_turn(session_id):
                    break
                sentence_callback(sentence)
                if idx < len(sentences) - 1:
                    time.sleep(vc_get("llm.mock_sleep_ms", 50) / 1000.0)
        total_latency_ms = int((time.time() - start_time) * 1000)
        telemetry_bus.push("llm_complete", {"latency_ms": total_latency_ms, "provider": "groq_mock"}, session_id, turn_id)
        cache_client.store(session_id, query, full_text, system_prompt, model_name, messages)
        return full_text

    # ------------------------------------------------------------------ #
    # 3. Circuit breaker open — OpenAI fallback (streaming)               #
    # ------------------------------------------------------------------ #
    if failover.primary_circuit_breaker.is_open():
        logger.log(
            event_name="llm_failover_triggered",
            session_id=session_id,
            turn_id=turn_id,
            detail={"reason": "circuit_breaker_open (streaming path)"},
        )
        full_text = failover._call_fallback(session_id, turn_id, messages, sentence_callback)
        cache_client.store(session_id, query, full_text, system_prompt, model_name, messages)
        return full_text

    # ------------------------------------------------------------------ #
    # 4. Live Groq streaming with sentence-boundary splitting              #
    # ------------------------------------------------------------------ #
    sentence_re = _get_sentence_re()

    budget = get_token_budget(session_id)
    context_history = prepare_context(messages, session_id)
    # Inject short-sentence directive to minimise TTFA — the LLM generates
    # shorter clauses so the first TTS dispatch happens sooner.  We prepend
    # rather than replace so the full persona prompt is preserved.
    latency_prompt = (
        "IMPORTANT: Keep every sentence very short and punchy (10 words max). "
        "Speak in short bursts — never write a long opening clause. " + system_prompt
    )
    payload = [{"role": "system", "content": latency_prompt}] + context_history

    prompt_tokens = estimate_tokens(system_prompt) + sum(
        estimate_tokens(m.get("content", "")) for m in context_history
    )
    budget.record_prompt(prompt_tokens)

    final_max_tokens = max_tokens if max_tokens is not None else vc_get("llm.max_tokens", 256)
    model_to_use = select_model(query)
    start_time = time.time()

    try:
        if model_to_use.startswith("openai/") or model_to_use.startswith("gpt-"):
            import openai
            kw = {"api_key": settings.openai_api_key or "dummy"}
            if settings.openai_base_url:
                kw["base_url"] = settings.openai_base_url
            client = openai.OpenAI(**kw)
            chat_completion = client.chat.completions.create(
                messages=payload,
                model=model_to_use,
                stream=True,
                max_tokens=final_max_tokens,
            )
        else:
            from groq import Groq
            client = Groq(api_key=api_key)
            chat_completion = client.chat.completions.create(
                messages=payload,
                model=model_to_use,
                stream=True,
                max_tokens=final_max_tokens,
            )
    except Exception as connect_err:
        # Groq connect failed — fall back to OpenAI synchronously
        failover.primary_circuit_breaker.record_failure(session_id, turn_id)
        telemetry_bus.push("llm_failover_triggered", {"reason": str(connect_err)}, session_id, turn_id)
        logger.log(
            event_name="llm_failover_triggered",
            session_id=session_id,
            turn_id=turn_id,
            detail={"reason": f"groq_connect_failed: {connect_err}"},
        )
        full_text = failover._call_fallback(session_id, turn_id, messages, sentence_callback)
        cache_client.store(session_id, query, full_text, system_prompt, model_name, messages)
        return full_text

    collected_chunks: list[str] = []
    sentence_buffer: list[str] = []
    first_token_fired = False

    try:
        for chunk in chat_completion:
            from services.orchestrator.async_pipeline import get_current_turn
            if cancellation_manager.is_cancelled(session_id) or int(turn_id) < get_current_turn(session_id):
                logger.log(
                    event_name="llm_cancelled",
                    session_id=session_id,
                    turn_id=turn_id,
                    detail={"msg": "LLM token stream aborted mid-turn."},
                )
                return "".join(collected_chunks)

            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue

            collected_chunks.append(delta)
            sentence_buffer.append(delta)

            if not first_token_fired:
                first_token_fired = True
                latency_ms = int((time.time() - start_time) * 1000)
                telemetry_bus.push("llm_first_token", {"latency_ms": latency_ms}, session_id, turn_id)
                logger.log(
                    event_name="llm_first_token",
                    session_id=session_id,
                    turn_id=turn_id,
                    latency_ms=latency_ms,
                    detail={},
                )

            # Flush complete sentences found in the accumulated buffer.
            buffered = "".join(sentence_buffer)
            parts = sentence_re.split(buffered)
            if len(parts) > 1:
                for sentence in parts[:-1]:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    # Re-check cancellation immediately before each dispatch
                    from services.orchestrator.async_pipeline import get_current_turn
                    if cancellation_manager.is_cancelled(session_id) or int(turn_id) < get_current_turn(session_id):
                        return "".join(collected_chunks)
                    sentence_callback(sentence)
                sentence_buffer = [parts[-1]]


    except Exception:
        failover.primary_circuit_breaker.record_failure(session_id, turn_id)
        raise

    failover.primary_circuit_breaker.record_success()

    # Flush any remaining buffer as the last sentence
    remaining = "".join(sentence_buffer).strip()
    from services.orchestrator.async_pipeline import get_current_turn
    if remaining and not cancellation_manager.is_cancelled(session_id) and int(turn_id) >= get_current_turn(session_id):
        sentence_callback(remaining)

    full_text = "".join(collected_chunks)
    total_latency_ms = int((time.time() - start_time) * 1000)
    completion_tok = estimate_tokens(full_text)
    budget = get_token_budget(session_id)
    budget.record_completion(completion_tok)
    telemetry_bus.push("llm_complete", {
        "latency_ms": total_latency_ms,
        "provider": "groq",
        "prompt_tokens": budget.prompt_tokens,
        "completion_tokens": completion_tok,
    }, session_id, turn_id)
    logger.log(
        event_name="llm_complete",
        session_id=session_id,
        turn_id=turn_id,
        latency_ms=total_latency_ms,
        detail={
            "provider": "groq",
            "prompt_tokens": budget.prompt_tokens,
            "completion_tokens": completion_tok,
            "budget_pct": budget.usage_pct,
        },
    )

    cache_client.store(session_id, query, full_text, system_prompt, model_name, messages)
    return full_text
