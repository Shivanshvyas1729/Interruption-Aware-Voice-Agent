"""
ingest.py — Phase 9 deliverable.

CORRECTED WIRING
-----------------
    orchestrator.out-telemetry -> observability-stack.in-telemetry

(the original uploaded architecture JSON sourced this from
orchestrator.in-word-ts, an input port used backwards — see
docs/pivot-build-plan.md section 0)

WHAT TO IMPLEMENT
------------------
- This is mostly CONFIGURATION, not custom code: stand up an
  OpenTelemetry Collector + Prometheus + Grafana + Loki, per
  docker-compose.yml's commented-out Phase 9 block (uncomment it here).
- receive_telemetry(metric_batch): the collector's ingest endpoint that
  services/orchestrator/telemetry.py.export_metrics() pushes to.
- Two Grafana dashboards, minimum, matching the PRD's headline
  non-functional metrics:
    1. Barge-in kill latency (p95) over time
    2. End-to-end turnaround (p95) over time
  Both should be able to show per-session and aggregate views, since
  Phase 9 also needs to prove these hold under 2-3 concurrent sessions.

CONFIG FILES TO ADD HERE (once implemented)
-----------------------------------------------
- prometheus.yml
- grafana/provisioning/dashboards/*.json
- otel-collector-config.yml

RELATED
-------
- services/orchestrator/telemetry.py
- docker-compose.yml (Phase 9 block)
- tests/phase9/test_failure_modes.py, test_concurrency.py
- docs/pivot-build-plan.md section 5, non-functional target tracker
"""

# TODO(phase-9): stand up prometheus/grafana/loki/otel-collector configs;
#                implement receive_telemetry; build the two dashboards
