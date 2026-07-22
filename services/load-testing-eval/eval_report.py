"""
eval_report.py -- Phase 11 deliverable: session-level latency eval report.

Reads logs/turn_timeline.log (JSONL -- one record per turn), aggregates all
completed turns across sessions, computes p95 latency percentiles, checks
against PRD non-functional targets, and outputs:
  1. Machine-readable  -> logs/eval_report.json
  2. Human-readable    -> printed to stdout and returned as str

PRD Non-functional Targets (from docs/pivot-build-plan.md):
  - Barge-in kill latency  < 300ms  p95
  - End-to-end turnaround  < 1500ms p95

Usage (standalone):
    python -m services.load-testing-eval.eval_report
    python services/load-testing-eval/eval_report.py --log logs/turn_timeline.log
"""
from __future__ import annotations

import json
import math
import os
import sys
import argparse
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# PRD targets
TARGET_BARGE_IN_KILL_P95_MS: float = 300.0
TARGET_TURNAROUND_P95_MS: float = 1500.0

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
DEFAULT_LOG_PATH = _ROOT / "logs" / "turn_timeline.log"
DEFAULT_OUT_PATH = _ROOT / "logs" / "eval_report.json"


@dataclass
class LatencyStat:
    count: int
    p50: Optional[float]
    p95: Optional[float]
    p99: Optional[float]
    mean: Optional[float]
    min_val: Optional[float]
    max_val: Optional[float]
    samples: List[float] = field(default_factory=list, repr=False)

    def meets_target(self, target_ms: float) -> Optional[bool]:
        if self.p95 is None:
            return None
        return self.p95 <= target_ms


@dataclass
class EvalReport:
    generated_at: str
    log_path: str
    total_turns_in_log: int
    completed_turns: int
    cancelled_turns: int
    superseded_turns: int
    error_turns: int
    llm_ttft: LatencyStat
    tts_ttfc: LatencyStat
    barge_in_kill: LatencyStat
    end_to_end_turnaround: LatencyStat
    barge_in_kill_p95_passes: Optional[bool]
    turnaround_p95_passes: Optional[bool]
    overall_pass: bool
    summary: str = ""


def _percentile(sorted_vals: List[float], pct: float) -> Optional[float]:
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * pct / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    if lo == hi:
        return round(sorted_vals[lo], 2)
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo), 2)


def _stat(samples: List[float]) -> LatencyStat:
    s = sorted(samples)
    return LatencyStat(
        count=len(s),
        p50=_percentile(s, 50),
        p95=_percentile(s, 95),
        p99=_percentile(s, 99),
        mean=round(sum(s) / len(s), 2) if s else None,
        min_val=round(s[0], 2) if s else None,
        max_val=round(s[-1], 2) if s else None,
        samples=s,
    )


def _ms(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    diff = (b - a) * 1000.0
    if diff < 0:
        return None
    return round(diff, 2)


def run_full_eval(
    log_path: Optional[str | Path] = None,
    out_path: Optional[str | Path] = None,
) -> EvalReport:
    """
    Read turn_timeline.log, compute p95 latency stats, check PRD targets.
    Returns EvalReport with machine-readable data and human-readable .summary.
    Writes JSON to out_path (default: logs/eval_report.json).
    """
    log_path = Path(log_path) if log_path else DEFAULT_LOG_PATH
    out_path = Path(out_path) if out_path else DEFAULT_OUT_PATH

    if not log_path.exists():
        raise FileNotFoundError(
            f"turn_timeline.log not found at {log_path}. "
            "Run the voice agent at least once to generate it."
        )

    all_turns: List[Dict[str, Any]] = []
    with open(log_path, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                all_turns.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    total = len(all_turns)
    completed: List[Dict] = []
    cancelled = 0
    superseded = 0
    error_count = 0

    for t in all_turns:
        cancel_reason = t.get("cancellation_reason")
        has_errors = bool(t.get("errors"))
        if cancel_reason == "superseded":
            superseded += 1
            continue
        if cancel_reason is not None:
            cancelled += 1
        if has_errors:
            error_count += 1
        if t.get("llm_request_sent") is not None:
            completed.append(t)

    llm_ttft_samples: List[float] = []
    tts_ttfc_samples: List[float] = []
    barge_in_samples: List[float] = []
    turnaround_samples: List[float] = []

    for t in completed:
        gaps = t.get("gaps", {})
        v = gaps.get("llm_request_to_first_token_ms")
        if v is not None and v >= 0:
            llm_ttft_samples.append(v)
        v = gaps.get("tts_request_to_first_chunk_ms")
        if v is not None and v >= 0:
            tts_ttfc_samples.append(v)
        v = gaps.get("vad_to_stt_start_ms")
        if v is not None and v >= 0:
            barge_in_samples.append(v)
        e2e = _ms(t.get("llm_request_sent"), t.get("playback_end"))
        if e2e is not None:
            turnaround_samples.append(e2e)

    llm_stat = _stat(llm_ttft_samples)
    tts_stat = _stat(tts_ttfc_samples)
    barge_stat = _stat(barge_in_samples)
    turnaround_stat = _stat(turnaround_samples)

    barge_passes = barge_stat.meets_target(TARGET_BARGE_IN_KILL_P95_MS)
    turn_passes = turnaround_stat.meets_target(TARGET_TURNAROUND_P95_MS)
    overall_pass = bool(
        (barge_passes is None or barge_passes)
        and (turn_passes is None or turn_passes)
    )

    def _fmt(stat: LatencyStat, target_ms: Optional[float] = None) -> str:
        if stat.count == 0:
            return "(no data)"
        badge = ""
        if target_ms is not None and stat.p95 is not None:
            badge = " PASS" if stat.p95 <= target_ms else " FAIL"
        return (
            f"n={stat.count}  p50={stat.p50}ms  p95={stat.p95}ms{badge}"
            f"  p99={stat.p99}ms  mean={stat.mean}ms  min={stat.min_val}ms  max={stat.max_val}ms"
        )

    overall_badge = "ALL TARGETS MET" if overall_pass else "ONE OR MORE TARGETS MISSED"
    summary_lines = [
        "=" * 72,
        "  PIVOT Phase 11 -- Full Session Latency Eval Report",
        f"  Generated : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"  Source    : {log_path}",
        "=" * 72,
        "",
        "TURN BREAKDOWN",
        f"  Total turns in log    : {total}",
        f"  Completed (LLM hit)   : {len(completed)}",
        f"  Cancelled (user/barge): {cancelled}",
        f"  Superseded (skipped)  : {superseded}",
        f"  Turns with errors     : {error_count}",
        "",
        "LATENCY STATS",
        "  LLM TTFT (request -> first token)",
        f"    {_fmt(llm_stat)}",
        "  TTS TTFC (request -> first audio chunk)",
        f"    {_fmt(tts_stat)}",
        f"  Barge-in Kill (VAD->STT start) [PRD target: p95 < {TARGET_BARGE_IN_KILL_P95_MS:.0f}ms]",
        f"    {_fmt(barge_stat, TARGET_BARGE_IN_KILL_P95_MS)}",
        f"  End-to-End Turnaround (LLM request->playback end) [PRD target: p95 < {TARGET_TURNAROUND_P95_MS:.0f}ms]",
        f"    {_fmt(turnaround_stat, TARGET_TURNAROUND_P95_MS)}",
        "",
        "PRD NON-FUNCTIONAL TARGETS",
        f"  Barge-in kill p95   : {'PASS' if barge_passes else ('FAIL' if barge_passes is False else 'N/A (no barge-in data)')}",
        f"  Turnaround p95      : {'PASS' if turn_passes else ('FAIL' if turn_passes is False else 'N/A (insufficient data)')}",
        "",
        f"  OVERALL: {overall_badge}",
        "=" * 72,
    ]
    summary = "\n".join(summary_lines)

    report = EvalReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        log_path=str(log_path),
        total_turns_in_log=total,
        completed_turns=len(completed),
        cancelled_turns=cancelled,
        superseded_turns=superseded,
        error_turns=error_count,
        llm_ttft=llm_stat,
        tts_ttfc=tts_stat,
        barge_in_kill=barge_stat,
        end_to_end_turnaround=turnaround_stat,
        barge_in_kill_p95_passes=barge_passes,
        turnaround_p95_passes=turn_passes,
        overall_pass=overall_pass,
        summary=summary,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    report_dict = asdict(report)
    for key in ("llm_ttft", "tts_ttfc", "barge_in_kill", "end_to_end_turnaround"):
        report_dict[key].pop("samples", None)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report_dict, fh, indent=2)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PIVOT Phase 11 Eval Report")
    parser.add_argument("--log", default=str(DEFAULT_LOG_PATH), help="Path to turn_timeline.log")
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH), help="Path for eval_report.json output")
    args = parser.parse_args()

    try:
        report = run_full_eval(log_path=args.log, out_path=args.out)
        print(report.summary)
        print(f"\nMachine-readable report written -> {args.out}")
        sys.exit(0 if report.overall_pass else 1)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
