# docs/architecture/

This directory holds the machine-readable architecture graph as it evolves.

- The ORIGINAL uploaded `architecture-*.json` had 22 of 35 edges violating
  basic port-direction rules (inputs used as sources, outputs used as
  targets, generic placeholder ports used instead of real named ones).
  Full audit table: `../pivot-build-plan.md`, section 0.
- Do not copy that file's literal edges into code. Build against the
  "Corrected reference data flow" in that same section instead.
- Once `scripts/validate_architecture.py` is implemented (Phase 0), the
  corrected graph should be saved here (e.g. `pivot.json`) and validated in
  CI on every change — including every sponsor-tech addition in Phase 8 —
  so this class of bug can't silently reappear.
