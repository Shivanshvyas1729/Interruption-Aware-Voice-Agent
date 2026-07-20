import asyncio
import time
import sys
from unittest.mock import patch
from services.orchestrator.async_pipeline import get_pipeline, get_cancel_token
from common.config.settings import get_settings

async def run_cancellation_test():
    settings = get_settings()
    orig_env = settings.env
    settings.env = "test"

    pipeline = get_pipeline()
    pipeline.start()

    session_id = "test-session-verify-cancellation"
    playback_queue = asyncio.Queue()
    pipeline.register_playback_client(session_id, playback_queue)

    latencies = []
    passes = 0
    fails = 0
    runs = 25

    print(f"Starting cancellation verification ({runs} runs)...")

    for run in range(1, runs + 1):
        # Reset token state using its public reset() method
        token = get_cancel_token(session_id)
        token.reset()

        # Flush queue
        while not playback_queue.empty():
            playback_queue.get_nowait()

        # Submit transcript
        await pipeline.submit_transcript(session_id, f"hello world run {run}", run)
        
        # Wait a short delay to ensure it gets in-flight
        await asyncio.sleep(0.08)

        # Cancel the session mid-flight
        t_cancel = time.time()
        await pipeline.submit_cancel(session_id, "user_interruption")

        # Poll the queue for 1.0s and verify silence latency
        t_last_arrival = None
        start_poll = time.time()
        while time.time() - start_poll < 1.0:
            try:
                item = await asyncio.wait_for(playback_queue.get(), timeout=0.05)
                # If we received something, record when it arrived
                t_last_arrival = time.time()
            except asyncio.TimeoutError:
                pass

        if t_last_arrival is not None:
            # Latency is from cancel invocation to the very last chunk that slipped through
            latency = (t_last_arrival - t_cancel) * 1000.0
        else:
            latency = 0.0

        # We assert that after cancellation sets is_cancelled, nothing is put to queue
        # Any arrival must have happened immediately (within 200ms budget)
        if latency <= 200.0:
            passes += 1
            latencies.append(latency)
        else:
            fails += 1
            print(f"  Run {run} failed: Received chunks {latency:.1f}ms after cancellation")

    pipeline.unregister_playback_client(session_id)
    await pipeline.stop()
    settings.env = orig_env

    print("\n--- Cancellation Verification Results ---")
    print(f"Passes: {passes} / {runs}")
    print(f"Fails: {fails} / {runs}")
    if latencies:
        print(f"Cancel-to-silence Latency Distribution:")
        print(f"  Min:    {min(latencies):.2f} ms")
        print(f"  Median: {sorted(latencies)[len(latencies)//2]:.2f} ms")
        print(f"  Max:    {max(latencies):.2f} ms")
    else:
        print("  No chunks received post-cancellation.")

    if fails > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(run_cancellation_test())
