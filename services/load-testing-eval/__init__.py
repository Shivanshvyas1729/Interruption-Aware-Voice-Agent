"""services.load_testing_eval — Load Testing & Eval service.

Two distinct jobs live here per the architecture's "Load Testing & Eval"
node, and they land in different phases:
  1. Concurrent-session LOAD generation (Phase 9).
  2. The automated 20-scenario interruption EVAL harness and final report
     (Phase 4 introduces the eval itself inside orchestrator's test suite;
     this service is what runs it repeatably/at scale and produces the
     Phase 11 final report).
"""
