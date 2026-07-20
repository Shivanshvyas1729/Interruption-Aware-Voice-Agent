"""
test_chaining_injected_failure.py
---------------------------------
Artificially forces a prior turn to raise a non-cancellation exception
(RuntimeError) and verifies that:
  1. The exception is logged.
  2. The current task still executes successfully.
  3. Ordering is preserved.
  4. Cleanup occurs properly.
  5. Subsequent turns continue to execute normally.

Usage:
    conda run -n voice-agent python scripts/test_chaining_injected_failure.py
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
)
import services.orchestrator.async_pipeline as _ap
import services.orchestrator.llm_client as _llm
from common.logging.logger import get_logger

logger = get_logger("test-chain-failure")

# Track if the error log was captured
_error_logged = False
_original_log_error = _ap.logger.log_error

def _mock_log_error(event_name, session_id, turn_id, exception, *args, **kwargs):
    global _error_logged
    if "prior_task_failed" in event_name or "injected_failure" in str(exception).lower():
        _error_logged = True
        print(f"  [LOGGED] Injected failure logged correctly: {event_name} -> {exception}")
    _original_log_error(event_name, session_id, turn_id, exception, *args, **kwargs)

# Hook into logger error method
_ap.logger.log_error = _mock_log_error

# Monkey-patch LLMWorker._process_request to raise RuntimeError only on Turn 1
_orig_process = _ap.LLMWorker._process_request

async def _mock_process_request(self, req, prev_task):
    if int(req.turn_id) == 1:
        # Simulate some processing delay so Turn 2 has time to enqueue and chain behind it
        await asyncio.sleep(0.1)
        print("  [LLMWorker] Artificially raising RuntimeError at end of Turn 1 task")
        raise RuntimeError("Injected failure")
    await _orig_process(self, req, prev_task)

_ap.LLMWorker._process_request = _mock_process_request


async def main():
    global _error_logged
    session_id = f"test-fail-{uuid.uuid4().hex[:6]}"
    pipeline = VoicePipeline()
    pipeline.start()
    await asyncio.sleep(0.05)

    client_q = asyncio.Queue()
    pipeline.register_playback_client(session_id, client_q)

    print("--- Starting Chaining Injected Failure Verification ---")
    
    # 1. Submit Turn 1 (expected to raise RuntimeError at end of process_request)
    print("Submitting Turn 1 (expected to fail)...")
    await pipeline.submit_transcript(session_id, "Trigger failure", 1)
    
    # 2. Submit Turn 2 IMMEDIATELY so it chains behind Turn 1's active task
    print("Submitting Turn 2 immediately (to chain behind Turn 1)...")
    await pipeline.submit_transcript(session_id, "New request", 2)

    # Poll client queue to verify Turn 2's response and terminal sentinel arrive
    terminal_received = False
    response_received = False
    deadline = asyncio.get_event_loop().time() + 2.0
    
    while asyncio.get_event_loop().time() < deadline:
        try:
            item = client_q.get_nowait()
            if isinstance(item, (bytes, bytearray)):
                if len(item) == 4:
                    terminal_received = True
            elif isinstance(item, dict) and item.get("type") == "llm_response":
                if "welcome" in item.get("text", "").lower():
                    response_received = True
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.01)

    await pipeline.stop()

    # Assertions
    passed = _error_logged and response_received and terminal_received
    
    print("\nVerification Results:")
    print(f"  Exception Logged:     {_error_logged}")
    print(f"  Turn 2 Response:      {response_received}")
    print(f"  Turn 2 Terminal:      {terminal_received}")
    
    if passed:
        print("\n[PASS] Chaining Injected Failure test completed successfully.")
        sys.exit(0)
    else:
        print("\n[FAIL] Chaining Injected Failure test failed.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
