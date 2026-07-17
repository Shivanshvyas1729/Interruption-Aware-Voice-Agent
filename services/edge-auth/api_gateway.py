"""
api_gateway.py — Phase 1 deliverable (routing), Phase 10 hardened (auth
enforcement + rate limiting).

CORRECTED WIRING
-----------------
    web-client.out-auth -> api-gateway.in
    api-gateway.out -> consent-service.in-consent-req
    token-service.out-auth-res -> api-gateway (generic inbound port)
    api-gateway -> web-client.in-auth
    api-gateway -> secrets-manager.in   (internal-api, for signing keys)

(the original uploaded architecture JSON sourced the client->gateway edge
from out-audio instead of out-auth, and the gateway->client return edge
targeted in-audio instead of in-auth — see docs/pivot-build-plan.md
section 0)

WHAT TO IMPLEMENT (Phase 1)
------------------------------
- POST /auth: receives the client's auth request, forwards to
  consent_service.check_consent(), then on approval routes to
  token_service.issue_token() and returns the LiveKit room token to the
  client. This is what client/phase1_minimal_harness/app.js's
  connectToRoom(token) actually calls to get a token in the first place —
  wire this before Phase 1's single-turn test can run against a real (not
  hardcoded) token.

WHAT TO IMPLEMENT (Phase 10)
--------------------------------
- Enforce auth on every non-/auth, non-/health route.
- Rate limiting per session_id / IP.

LOG EVENTS
----------
- auth_request_received { session_id }
- auth_request_routed   { session_id, outcome }

RELATED
-------
- services/edge-auth/consent_service.py
- services/edge-auth/token_service.py
- tests/phase1/test_single_turn.py (should exercise this path, not bypass it)
- tests/phase10/test_security_checklist.py
"""

# TODO(phase-1): implement POST /auth routing to consent_service + token_service
# TODO(phase-10): implement auth enforcement + rate limiting
