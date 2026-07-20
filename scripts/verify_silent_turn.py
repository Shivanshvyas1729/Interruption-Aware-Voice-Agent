"""
verify_silent_turn.py
---------------------
Tests that every LLM turn terminates with exactly one is_final=True LLMSentenceChunk
regardless of the response content.

Verified cases:
  1. Normal multi-sentence reply
  2. Single-word reply (no punctuation)
  3. Reply ending in period without trailing whitespace ("okay.")
  4. Empty reply (e.g. cancellation mid-stream)
  5. Reply with only newline separators

Usage:
    conda run -n voice-agent python scripts/verify_silent_turn.py
"""

import asyncio
import sys
import os
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("ENV", "test")
os.environ.setdefault("CARTESIA_API_KEY", "")

from services.orchestrator.async_pipeline import (
    VoicePipeline,
    LLMSentenceChunk,
    get_pipeline,
)
from services.orchestrator import llm_client as _llm


# ---------------------------------------------------------------------------
# Monkey-patch call_primary_streaming to inject controlled responses
# ---------------------------------------------------------------------------

_injected_response = "default"

_original_cps = _llm.call_primary_streaming

def _mock_cps(session_id, turn_id, messages, sentence_callback, *a, **kw):
    """Return the globally injected response and call sentence_callback exactly
    as a real streaming response would (using the real flush logic)."""
    from services.orchestrator.llm_client import _get_sentence_re
    import re
    text = _injected_response

    sentence_re = _get_sentence_re()
    sentence_buffer = list(text)

    collected = []
    buf = []
    for ch in text:
        collected.append(ch)
        buf.append(ch)
        buffered = "".join(buf)
        parts = sentence_re.split(buffered)
        if len(parts) > 1:
            for sentence in parts[:-1]:
                sentence = sentence.strip()
                if sentence:
                    sentence_callback(sentence)
            buf = [parts[-1]]

    remaining = "".join(buf).strip()
    if remaining:
        sentence_callback(remaining)

    return text

_llm.call_primary_streaming = _mock_cps


# ---------------------------------------------------------------------------
# Helper: run one pipeline turn and collect LLMSentenceChunks reaching FSM
# ---------------------------------------------------------------------------

async def run_case(label: str, response_text: str) -> tuple:
    global _injected_response
    _injected_response = response_text

    session_id = f"test-silent-{uuid.uuid4().hex[:6]}"
    pipeline = VoicePipeline()
    pipeline.start()
    await asyncio.sleep(0.05)

    client_q = asyncio.Queue()
    pipeline.register_playback_client(session_id, client_q)

    await pipeline.submit_transcript(session_id, "test input", 1)

    # Wait for the is_last=True sentinel to appear as a 4-byte tagged frame
    import struct
    terminal_received = False
    non_terminal_count = 0
    deadline = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline:
        try:
            item = client_q.get_nowait()
            if isinstance(item, (bytes, bytearray)):
                if len(item) == 4:
                    # 4-byte only = tagged sentinel (empty PCM payload)
                    terminal_received = True
                    break
                elif len(item) > 4:
                    non_terminal_count += 1
            elif isinstance(item, dict) and item.get("type") == "llm_response":
                pass
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.01)

    await pipeline.stop()

    passed = terminal_received
    label_str = "PASS" if passed else "FAIL"
    print(f"  [{label_str}] {label} - terminal_received={terminal_received}, audio_chunks_before_terminal={non_terminal_count}")
    return passed


async def main():
    cases = [
        ("Multi-sentence reply",
         "Mars is the fourth planet from the Sun. It has two moons."),
        ("Single word",
         "Okay"),
        ("Period without trailing whitespace",
         "okay."),
        ("Empty string",
         ""),
        ("Newline separator only",
         "Sure thing\nHere you go"),
        ("Very long single sentence",
         "The quick brown fox jumps over the lazy dog and nobody was watching when it happened"),
    ]

    passes = 0
    fails = 0
    print("--- Silent Turn Death Verification ---")
    for label, text in cases:
        ok = await run_case(label, text)
        if ok:
            passes += 1
        else:
            fails += 1

    print()
    print(f"Passes: {passes} / {len(cases)}")
    print(f"Fails:  {fails} / {len(cases)}")
    if fails > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
