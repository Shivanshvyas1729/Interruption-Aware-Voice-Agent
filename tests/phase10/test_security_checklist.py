"""
Phase 10 test gate — see docs/pivot-build-plan.md Phase 10.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- Unauthenticated requests to any endpoint requiring auth are rejected.
- Secrets (anything matching common/logging/logger.py's scrub-list) never
  appear in captured log output, across every event type defined in
  common/events/event_names.py — not just the ones written in Phase 0.
- A session with consent denied (consent-service) never reaches the STT
  stage — no audio is processed without consent.

Un-skip as part of the Phase 10 prompt.
"""
import pytest


@pytest.mark.skip(reason="Phase 10 not yet implemented — see PHASE_PROMPTS.md")
def test_auth_secrets_and_consent_are_enforced():
    ...
