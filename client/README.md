# client/

The structure of the client-side code:

- `phase1_minimal_harness/` — the primary production user interface and canonical frontend for the Pivot voice agent. Contains the complete WebRTC, LiveKit, Voice Activity Detection (VAD), interruption handling, configuration, and latency monitoring dashboards.

- `src/` — React app shell. Note that all ongoing features, UI improvements, and integrations directly target the primary production application in `phase1_minimal_harness/`.

