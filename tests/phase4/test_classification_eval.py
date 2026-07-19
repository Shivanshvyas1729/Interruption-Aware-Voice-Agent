import os
import json
import pytest
from services.orchestrator.interruption_classifier import classify, is_backchannel
from services.orchestrator.fsm import get_fsm_for_session, _fsms

os.environ["ENV"] = "test"
os.environ["ACTIVE_PHASE"] = "4"
os.environ["SECRETS_BACKEND"] = "local"

def test_interruption_classification_accuracy_20_scenarios():
    # 1. Load the 20 scenario fixtures
    fixture_path = os.path.join("tests", "phase4", "fixtures", "scenarios.json")
    with open(fixture_path, "r") as f:
        data = json.load(f)
        
    scenarios = data["scenarios"]
    assert len(scenarios) == 20
    
    passed_count = 0
    results_table = []
    
    # 2. Evaluate each scenario
    for idx, scenario in enumerate(scenarios):
        text = scenario["text"]
        expected = scenario["expected_type"]
        
        classification = classify(text)
        actual = classification["type"]
        
        passed = (actual == expected)
        if passed:
            passed_count += 1
            
        results_table.append({
            "id": idx + 1,
            "text": text,
            "expected": expected,
            "actual": actual,
            "status": "PASS" if passed else "FAIL"
        })
        
    accuracy = (passed_count / len(scenarios)) * 100
    
    # 3. Print markdown results table for the logs
    print("\n\n### Interruption Classification Evaluation Results")
    print(f"**Overall Accuracy: {accuracy:.1f}% (Required: >=85.0%)**\n")
    print("| ID | Scenario Text | Expected Type | Classified Type | Status |")
    print("|----|---------------|---------------|-----------------|--------|")
    for r in results_table:
        print(f"| {r['id']} | {r['text']} | {r['expected']} | {r['actual']} | {r['status']} |")
        
    # Assert classification accuracy target
    assert accuracy >= 85.0

def test_backchannel_does_not_trigger_barge_in():
    session_id = "session-test-phase4-backchannel"
    if session_id in _fsms:
        del _fsms[session_id]
        
    fsm = get_fsm_for_session(session_id)
    fsm.handle_media_event("participant_joined", {})
    assert fsm.state == "listening"
    
    # Simulate speaking
    fsm.transition("speaking")
    assert fsm.state == "speaking"
    
    # 1. Inject brief 'user_speech_start' (VAD start)
    # This represents noise or start of voice, but without confirmation of sustained speech (200ms)
    fsm.handle_media_event("user_speech_start", {})
    # State should remain speaking because it was not confirmed as sustained speech yet (filter threshold)
    assert fsm.state == "speaking"
    
    # 2. Send backchannel transcript segment
    # Even if it gets transcribed, it should be filtered out by is_backchannel
    fsm.receive_transcript("mm-hm")
    # State should remain speaking (or return to it if temporarily interrupted)
    assert fsm.state == "speaking"
