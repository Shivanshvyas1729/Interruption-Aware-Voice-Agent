"""services.observability_stack — Operations & Observability Layer.

Represents the actual Prometheus/Grafana/Loki/OpenTelemetry-collector
service the architecture calls "Observability Stack" — distinct from
services/orchestrator/telemetry.py, which is the CLIENT-side module that
sends metrics here. Phase 9 deliverable.
"""
