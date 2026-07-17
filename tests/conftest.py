import os
import sys
import types

# -----------------------------------------------------------------------------
# HYPHENATED PYTHON PACKAGE IMPORT ALIAS RESOLVER
# -----------------------------------------------------------------------------
# Pytest and service modules import absolute names with underscores
# (e.g. services.edge_auth.api_gateway). Since the directory names on disk
# contain hyphens (e.g. services/edge-auth/), standard imports raise a
# ModuleNotFoundError.
# This code injects alias modules into sys.modules at boot-time.
# -----------------------------------------------------------------------------

if "services" not in sys.modules:
    services_module = types.ModuleType("services")
    services_module.__path__ = [os.path.abspath("services")]
    sys.modules["services"] = services_module

hyphen_mappings = [
    ("edge-auth", "edge_auth"),
    ("media-gateway", "media_gateway"),
    ("task-worker", "task_worker")
]

for hyphen_name, underscore_name in hyphen_mappings:
    full_name = f"services.{underscore_name}"
    if full_name not in sys.modules:
        m = types.ModuleType(full_name)
        m.__path__ = [os.path.abspath(f"services/{hyphen_name}")]
        sys.modules[full_name] = m
