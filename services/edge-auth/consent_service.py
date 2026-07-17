"""
consent_service.py — Phase 1 deliverable (stub check), Phase 10 hardened
(actual enforcement gate).

CORRECTED WIRING
-----------------
    api-gateway.out -> consent-service.in-consent-req
    consent-service.out-consent-res -> token-service.in-auth-req

WHAT TO IMPLEMENT (Phase 1)
------------------------------
- check_consent(session_id, purpose="recording_and_processing") -> bool.
  Phase 1 can hardcode/approve everything (e.g. an in-memory allow-list or
  a simple flag) — the point of Phase 1 is proving the pipeline plumbing,
  not building full consent UX yet. Record this as a logged, deliberate
  simplification (ground rule #6), same pattern as the Phase 1 client
  harness deviation.

WHAT TO IMPLEMENT (Phase 10)
--------------------------------
- Replace the Phase 1 stub with a real consent record (per-session,
  persisted, revocable) and ACTUALLY BLOCK the flow: no session without
  recorded consent should ever reach deepgram-stt.in-audio. This is a
  named PRD requirement (Responsible AI / GDPR-applicability section) and
  a named Phase 10 test assertion — don't let the Phase 1 stub silently
  remain the permanent behavior.

LOG EVENTS
----------
- consent_checked  { session_id, outcome }
- consent_denied   { session_id, reason }   (Phase 10)

RELATED
-------
- tests/phase10/test_security_checklist.py — asserts a consent-denied
  session never reaches STT.
"""

# TODO(phase-1): implement check_consent (deliberately simple stub, log the simplification)
# TODO(phase-10): implement real consent records + hard enforcement gate
