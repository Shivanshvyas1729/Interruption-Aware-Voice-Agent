"""
Phase 11 test gate (final readiness) -- see docs/pivot-build-plan.md Phase 11.

Asserts:
- Barge-in kill latency < 300ms p95 (when barge-in data is available)
- End-to-end turnaround < 1500ms p95
- The eval report generates successfully from logs/turn_timeline.log
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

LOG_PATH = Path(__file__).parents[2] / "logs" / "turn_timeline.log"


def test_final_eval_meets_both_nonfunctional_targets():
    """Phase 11 gate: PRD latency targets must be met under real log data."""
    if not LOG_PATH.exists():
        pytest.skip(
            f"turn_timeline.log not found at {LOG_PATH}. "
            "Run the voice agent to generate it, then re-run this test."
        )

    from services.load_testing_eval.eval_report import run_full_eval

    report = run_full_eval(log_path=LOG_PATH)

    print("\n" + report.summary)

    assert report.completed_turns > 0, (
        f"No completed turns found in {LOG_PATH}. "
        f"Total: {report.total_turns_in_log}, superseded: {report.superseded_turns}."
    )

    assert report.turnaround_p95_passes is not False, (
        f"End-to-end turnaround p95 = {report.end_to_end_turnaround.p95}ms "
        f"exceeds PRD target of 1500ms. "
        f"(n={report.end_to_end_turnaround.count} completed turns)"
    )

    if report.barge_in_kill.count > 0:
        assert report.barge_in_kill_p95_passes is not False, (
            f"Barge-in kill p95 = {report.barge_in_kill.p95}ms "
            f"exceeds PRD target of 300ms. "
            f"(n={report.barge_in_kill.count} barge-in events)"
        )
