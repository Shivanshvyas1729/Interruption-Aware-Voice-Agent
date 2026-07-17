"""
load_test.py — Phase 9 deliverable.

CORRECTED WIRING
-----------------
    load-testing-eval -> livekit-server.in-audio-client   (Simulated Load)

This is a legitimate SHARED use of in-audio-client (the same port the real
client uses) — a simulated client is still a client from LiveKit's point of
view. Not a bug, unlike the other findings in docs/pivot-build-plan.md
section 0.

WHAT TO IMPLEMENT (Phase 9)
------------------------------
- Using Locust (see requirements.txt) or an equivalent, simulate 2-3
  concurrent sessions each running a scripted multi-turn, multi-interruption
  conversation against fixture audio, and report whether:
    - latency budgets (barge-in <300ms p95, turnaround <1.5s p95) hold
    - no cross-session state leakage occurs (session A's Redis state never
      appears in session B's context)

RELATED
-------
- tests/phase9/test_concurrency.py
"""

# TODO(phase-9): implement concurrent-session load simulation + report
