"""
telemetry.py — base logging usage from Phase 0/1, OTEL export in Phase 9.

CORRECTED WIRING (Phase 9)
----------------------------
    orchestrator.out-telemetry -> observability-stack.in-telemetry

(the original uploaded JSON sourced this from in-word-ts, an input port,
backwards — see section 0)

WHAT TO IMPLEMENT (Phase 0/1)
---------------------------------
- Nothing new here yet — Phase 0/1 modules call common.logging.logger
  directly. This file exists as the eventual seam for Phase 9's OTEL export
  so that switch doesn't require touching every module that logs.

WHAT TO IMPLEMENT (Phase 9)
------------------------------
- export_metrics(): pushes the two headline non-functional metrics
  (barge-in kill latency, end-to-end turnaround) to Prometheus/OTEL, backing
  the Grafana dashboards.

RELATED
-------
- tests/phase9/test_failure_modes.py
- docs/pivot-build-plan.md section 5, non-functional target tracker
"""

# TODO(phase-9): implement export_metrics, OTEL wiring
