import asyncio
import time
import sys
import uuid
from services.orchestrator.async_pipeline import get_pipeline, get_cancel_token
from common.config.settings import get_settings
from services.orchestrator.state_store import load_history, clear_session

async def run_no_followup_test():
    settings = get_settings()
    orig_env = settings.env
    settings.env = "test"

    pipeline = get_pipeline()
    pipeline.start()

    runs = 15
    passes = 0
    fails = 0

    print(f"\nStarting no-followup interruption verification ({runs} runs)...")

    for run in range(1, runs + 1):
        session_id = f"test-nf-{uuid.uuid4().hex[:6]}"
        playback_queue = asyncio.Queue()
        pipeline.register_playback_client(session_id, playback_queue)

        # Clear state
        clear_session(session_id)
        get_cancel_token(session_id).reset()

        try:
            # 1. Submit first transcript
            await pipeline.submit_transcript(session_id, "What's the weather in Bhilwara?", 1)
            
            # Wait for the first audio chunk
            while True:
                item = await asyncio.wait_for(playback_queue.get(), timeout=2.0)
                if isinstance(item, bytes) and len(item) > 100:
                    break

            # 2. Interrupt immediately
            await pipeline.submit_cancel(session_id, "barge_in")
            
            # Flush queue post-cancellation
            start_poll = time.time()
            while time.time() - start_poll < 0.3:
                try:
                    await asyncio.wait_for(playback_queue.get(), timeout=0.01)
                except asyncio.TimeoutError:
                    pass

            # No follow-up transcript is submitted. Allow time to resolve
            await asyncio.sleep(0.3)

            # 3. Load history
            history = load_history(session_id)
            
            assistant_turns = [msg for msg in history if msg["role"] == "assistant"]
            user_turns = [msg for msg in history if msg["role"] == "user"]
            
            assert len(user_turns) == 1, f"Expected 1 user turn, got {len(user_turns)}"
            
            # Assistant turn must be truncated to only what was spoken,
            # or completely absent if 0 words were spoken, but NEVER the full "You're welcome!"
            if len(assistant_turns) > 0:
                truncated_turn = assistant_turns[0]["content"]
                print(f"Run {run} - Truncated turn (no followup): {truncated_turn!r}")
                assert truncated_turn != "You're welcome!", "Assistant response committed in full!"
            else:
                print(f"Run {run} - Assistant response discarded successfully (0 words spoken)")

            passes += 1
        except Exception as e:
            fails += 1
            print(f"Run {run} - FAILED: {e}")
        finally:
            pipeline.unregister_playback_client(session_id)
            clear_session(session_id)

    await pipeline.stop()
    settings.env = orig_env
    return passes, fails


async def run_correction_test():
    settings = get_settings()
    orig_env = settings.env
    settings.env = "test"

    pipeline = get_pipeline()
    pipeline.start()

    runs = 15
    passes = 0
    fails = 0

    print(f"\nStarting correction flow verification ({runs} runs)...")

    for run in range(1, runs + 1):
        session_id = f"test-corr-{uuid.uuid4().hex[:6]}"
        playback_queue = asyncio.Queue()
        pipeline.register_playback_client(session_id, playback_queue)

        clear_session(session_id)
        get_cancel_token(session_id).reset()

        try:
            await pipeline.submit_transcript(session_id, "What's the weather in Bhilwara?", 1)
            
            while True:
                item = await asyncio.wait_for(playback_queue.get(), timeout=2.0)
                if isinstance(item, bytes) and len(item) > 100:
                    break

            await pipeline.submit_cancel(session_id, "barge_in")
            
            start_poll = time.time()
            while time.time() - start_poll < 0.3:
                try:
                    await asyncio.wait_for(playback_queue.get(), timeout=0.01)
                except asyncio.TimeoutError:
                    pass

            await pipeline.submit_transcript(session_id, "Wait, I mean Jaipur", 2)
            
            while True:
                item = await playback_queue.get()
                if isinstance(item, dict) and item.get("type") == "llm_response":
                    break

            await asyncio.sleep(0.4)

            history = load_history(session_id)
            
            assistant_turns = [msg for msg in history if msg["role"] == "assistant"]
            user_turns = [msg for msg in history if msg["role"] == "user"]
            
            assert len(user_turns) >= 2, f"Expected at least 2 user turns, got {len(user_turns)}"
            assert user_turns[0]["content"] == "What's the weather in Bhilwara?"
            assert user_turns[1]["content"] == "Wait, I mean Jaipur"
            
            assert len(assistant_turns) >= 2, f"Expected 2 assistant turns, got {len(assistant_turns)}"
            truncated_turn = assistant_turns[0]["content"]
            
            print(f"Run {run} - Truncated turn: {truncated_turn!r}")
            assert truncated_turn != "You're welcome!", f"Assistant turn was NOT truncated! Got: {truncated_turn!r}"
            
            passes += 1
        except Exception as ae:
            fails += 1
            print(f"Run {run} - FAILED: {ae}")
        finally:
            pipeline.unregister_playback_client(session_id)
            clear_session(session_id)

    await pipeline.stop()
    settings.env = orig_env
    return passes, fails


async def main():
    nf_passes, nf_fails = await run_no_followup_test()
    corr_passes, corr_fails = await run_correction_test()
    
    print("\n--- Final Verification Summary ---")
    print(f"No-Followup Test: Passes = {nf_passes}, Fails = {nf_fails}")
    print(f"Correction Test:  Passes = {corr_passes}, Fails = {corr_fails}")
    
    if nf_fails > 0 or corr_fails > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
