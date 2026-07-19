"""services.edge_auth — Edge & Auth Layer: api-gateway, consent-service,
token-service, secrets-manager.

Added to close a real gap in the initial scaffold: these 4 architecture
nodes were referenced in docs/pivot-build-plan.md's corrected data flow but
had no file presence at all. Phase 1's client join flow depends on this
chain existing; Phase 10's security hardening depends on it being real by
then, not retrofitted.
"""
