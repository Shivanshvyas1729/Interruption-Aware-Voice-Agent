"""
verify_audio_delivery_timing.py
--------------------------------
Verifies that the backend server dispatches the first audio chunk
of a response turn before the final terminal LLM text response is sent.

Note: This verifies the server-side streaming dispatch order.
The client-side playback unblock logic resides in the browser (app.js)
and cannot be executed directly in this in-process Python script.
"""

import asyncio
import sys
import os
import time
import json
import uuid
from unittest.mock import patch

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force test/mock mode
os.environ.setdefault("ENV", "test")

# Override voice config settings to speed up TTS synthesis
from common.config import voice_settings
cfg = voice_settings.get_voice_config()
cfg["tts"] = cfg.get("tts", {})
cfg["tts"]["mock_sleep_ms"] = 5    # speed up TTS initial synthesis startup
cfg["tts"]["mock_chunk_sleep_ms"] = 2 # speed up TTS streaming chunks

from services.edge_auth.telemetry_bus import telemetry_bus
from services.orchestrator.async_pipeline import VoicePipeline

log_file = open("logs/verify_timing.log", "w", encoding="utf-8")

def log_print(msg):
    print(msg)
    log_file.write(msg + "\n")
    log_file.flush()

async def print_telemetry_loop(q, start_time):
    while True:
        try:
            event_json = await q.get()
            event = json.loads(event_json)
            elapsed = time.time() - start_time
            log_print(f"[Telemetry] +{elapsed:.4f}s: Event={event.get('type')} turn={event.get('turn_id')} session={event.get('session_id')}")
        except asyncio.CancelledError:
            break
        except Exception:
            pass

def mock_call_primary_streaming(session_id, turn_id, messages, sentence_callback, **kwargs):
    """Mocks a 3-sentence LLM stream with 300ms delays to guarantee Sentence 1
    gets dispatched through the Lookahead-1 buffer before the LLM completes."""
    text = "Mars is the fourth planet. It is red. It has two moons."
    sentences = ["Mars is the fourth planet.", "It is red.", "It has two moons."]
    for idx, s in enumerate(sentences):
        sentence_callback(s)
        time.sleep(0.3)  # simulate LLM stream sentence generation gap
    return text

async def main():
    session_id = f"test-timing-{uuid.uuid4().hex[:6]}"
    pipeline = VoicePipeline()
    pipeline.start()
    await asyncio.sleep(0.1)

    tel_q = asyncio.Queue()
    telemetry_bus.register(tel_q)

    client_q = asyncio.Queue()
    pipeline.register_playback_client(session_id, client_q)

    start_time = time.time()
    tel_task = asyncio.create_task(print_telemetry_loop(tel_q, start_time))

    log_print("[Test] Submitting transcript: 'Explain Mars.'")
    
    # Patch call_primary_streaming inside llm_client
    with patch("services.orchestrator.llm_client.call_primary_streaming", mock_call_primary_streaming):
        await pipeline.submit_transcript(session_id, "Explain Mars.", 1)

        first_audio_chunk_time = None
        llm_response_time = None

        deadline = start_time + 4.0

        while time.time() < deadline:
            if first_audio_chunk_time is not None and llm_response_time is not None:
                break
            try:
                item = client_q.get_nowait()
                arrival = time.time() - start_time
                if isinstance(item, (bytes, bytearray)):
                    if first_audio_chunk_time is None:
                        first_audio_chunk_time = arrival
                        log_print(f"[Test] First audio chunk arrived at: {arrival:.4f}s")
                elif isinstance(item, dict) and item.get("type") == "llm_response":
                    llm_response_time = arrival
                    log_print(f"[Test] Final LLM response arrived at: {arrival:.4f}s")
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.01)

    telemetry_bus.unregister(tel_q)
    tel_task.cancel()
    await pipeline.stop()

    log_print("\n--- Timing Analysis ---")
    if first_audio_chunk_time is None:
        log_print("FAIL: No audio chunks received.")
        log_file.close()
        sys.exit(1)
    if llm_response_time is None:
        log_print("FAIL: Final LLM response was never received.")
        log_file.close()
        sys.exit(1)

    delta = llm_response_time - first_audio_chunk_time
    log_print(f"First Audio Chunk Time: {first_audio_chunk_time:.4f}s")
    log_print(f"Final LLM Response Time: {llm_response_time:.4f}s")
    log_print(f"Difference (LLM text - First Audio): {delta:.4f}s ({delta*1000.0:.2f}ms)")

    if delta > 0:
        log_print("PASS: First audio chunk arrived BEFORE the final LLM text response.")
    else:
        log_print("FAIL: First audio chunk arrived at or after the final LLM response.")
        log_file.close()
        sys.exit(1)
    
    log_file.close()

if __name__ == "__main__":
    asyncio.run(main())
