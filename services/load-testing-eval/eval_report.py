"""
eval_report.py — Phase 11 deliverable (final reporting), building on
Phase 4's standing 20-scenario eval (see
tests/phase4/test_classification_eval.py, which stays the authoritative
implementation of the eval itself).

WHAT TO IMPLEMENT (Phase 11)
------------------------------
- run_full_eval() -> report combining:
    1. Classification accuracy across the 20 scenarios (from Phase 4's eval).
    2. Latency report: barge-in kill p95 and end-to-end turnaround p95,
       measured under the SAME concurrent-session conditions as Phase 9's
       load_test.py, not in isolation.
  Output as both a machine-readable artifact (for tests/phase11/test_full_eval.py
  to assert against) and a human-readable summary (for the demo-day writeup).

RELATED
-------
- tests/phase4/test_classification_eval.py
- tests/phase9/test_concurrency.py
- tests/phase11/test_full_eval.py
- docs/pivot-build-plan.md section 5, non-functional target tracker
"""

# TODO(phase-11): implement run_full_eval, machine + human readable output
