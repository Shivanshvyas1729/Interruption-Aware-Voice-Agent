"""services.media_gateway — LiveKit room/session glue (data plane).

Handles raw audio only. Never talks LLM/business logic — that's the
orchestrator's job, reached only via services.media_gateway.events on the
control plane. See docs/pivot-build-plan.md section 0 for the corrected
port-level wiring this package must implement.
"""
