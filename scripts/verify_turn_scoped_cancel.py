"""
verify_turn_scoped_cancel.py
----------------------------
Runs the exact barge-in reproduction from the Problem #5 prompt 15 times.
Asserts that ZERO AudioChunk objects tagged with a stale turn_id reach the
mock playback client queue after cancellation.

Usage:
    conda run -n voice-agent python scripts/verify_turn_scoped_cancel.py
"""

import asyncio
import sys
import os
import struct
import uuid

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force test/mock mode so TTS uses the mock path (no Cartesia API key needed)
os.environ.setdefault("ENV", "test")
os.environ.setdefault("CARTESIA_API_KEY", "")

from services.orchestrator.async_pipeline import (
    VoicePipeline,
    AudioChunk,
    get_current_turn,
)


async def run_single(run_num: int) -> tuple:
    """
    Returns (passed, stale_chunks_seen).
    passed is True when zero stale-turn bytes reach the client queue.
    """
    session_id = f"test-stale-{uuid.uuid4().hex[:6]}"
    pipeline = VoicePipeline()
    pipeline.start()
    await asyncio.sleep(0.05)  # let workers start

    # Register a mock playback client queue
    client_q = asyncio.Queue()
    pipeline.register_playback_client(session_id, client_q)

    # ---- Turn 1 ----
    await pipeline.submit_transcript(session_id, "What's the weather in Bhilwara?", 1)

    # Wait for the first audio chunk to arrive
    first_chunk_received = False
    deadline = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline:
        try:
            item = client_q.get_nowait()
            if isinstance(item, (bytes, bytearray)) and len(item) > 4:
                first_chunk_received = True
                break
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.01)

    # ---- Cancel + Turn 2 ----
    await pipeline.submit_cancel(session_id, "barge_in")
    await asyncio.sleep(0.01)  # let cancel propagate

    await pipeline.submit_transcript(session_id, "Wait, I mean Jaipur", 2)
    await asyncio.sleep(0.05)  # let turn_id advance

    turn2_id = get_current_turn(session_id)

    # Drain the queue and collect everything for up to 1.5s
    collected = []
    deadline = asyncio.get_event_loop().time() + 1.5
    while asyncio.get_event_loop().time() < deadline:
        try:
            item = client_q.get_nowait()
            if isinstance(item, (bytes, bytearray)):
                collected.append(bytes(item))
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.01)

    await pipeline.stop()

    # --- Analysis ---
    # Each bytes item is struct.pack("<I", turn_id) + pcm_data
    # Stale = tagged with turn_id < turn2_id
    stale_count = 0
    for raw in collected:
        if len(raw) < 4:
            continue
        tagged_turn_id = struct.unpack_from("<I", raw, 0)[0]
        if tagged_turn_id < turn2_id:
            stale_count += 1
            print(f"  Run {run_num}: STALE chunk - turn_id={tagged_turn_id} < current={turn2_id}")

    passed = stale_count == 0
    label = "PASS" if passed else "FAIL"
    print(f"Run {run_num}: {label} - stale_chunks={stale_count}, "
          f"current_turn={turn2_id}, total_collected={len(collected)}, "
          f"first_chunk_received={first_chunk_received}")
    return passed, stale_count


async def main():
    total_runs = 15
    passes = 0
    fails = 0
    total_stale = 0

    for i in range(1, total_runs + 1):
        passed, stale = await run_single(i)
        total_stale += stale
        if passed:
            passes += 1
        else:
            fails += 1

    print()
    print("--- Turn-Scoped Cancellation Verification Results ---")
    print(f"Passes: {passes} / {total_runs}")
    print(f"Fails:  {fails} / {total_runs}")
    print(f"Total stale AudioChunks forwarded to client: {total_stale}")

    if fails > 0 or total_stale > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
