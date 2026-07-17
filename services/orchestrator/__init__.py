"""services.orchestrator — control plane.

Handles transcripts and control signals ONLY — never raw audio (that stays
in services.media_gateway). This is the "main agent brain" per the PRD:
state management, interruption taxonomy, LLM routing, tool policy.

Grows by exactly one concern per phase. Do not reach ahead and implement a
later phase's module early — see docs/pivot-build-plan.md ground rule #4.
"""
