"""
token_service.py — Phase 1 deliverable.

CORRECTED WIRING
-----------------
    consent-service.out-consent-res -> token-service.in-auth-req
    secrets-manager.out -> token-service (signing keys)
    token-service.out-auth-res -> api-gateway

WHAT TO IMPLEMENT
------------------
- issue_token(session_id, room_name) -> a signed LiveKit room token, using
  LIVEKIT_API_KEY / LIVEKIT_API_SECRET (via secrets_manager, not raw env
  reads once Phase 10 lands — Phase 1 can read them via common.config
  directly, matching the rest of Phase 1's simplicity level).

LOG EVENTS
----------
- token_issued { session_id, room_name }

RELATED
-------
- services/media-gateway/room_manager.py — consumes the issued token to
  actually create/join the LiveKit room.
- tests/phase1/test_single_turn.py
"""

# TODO(phase-1): implement issue_token
