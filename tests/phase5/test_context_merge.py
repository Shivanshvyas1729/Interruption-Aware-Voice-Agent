import pytest
from services.orchestrator.context_merge import resolve
from services.orchestrator.state_store import save_turn, load_history, clear_session

def test_resolution_strategy_per_interruption_type():
    session_id = "test-phase5-session"
    
    # --- Helper to reset state store ---
    def setup_base_history():
        clear_session(session_id)
        save_turn(session_id, "1", "user", "What is the weather?")
        save_turn(session_id, "1", "assistant", "The weather is currently sunny and warm in Paris.")

    # 1. Test CORRECTION Strategy
    setup_base_history()
    res = resolve(
        session_id=session_id,
        spoken_words=["The", "weather", "is", "currently"],
        unspoken_words=["sunny", "and", "warm", "in", "Paris."],
        interruption_type="correction"
    )
    assert res["strategy"] == "correction"
    history = load_history(session_id)
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "The weather is currently"
    
    # 2. Test TOPIC-CHANGE Strategy
    setup_base_history()
    res = resolve(
        session_id=session_id,
        spoken_words=["The", "weather", "is"],
        unspoken_words=["currently", "sunny", "and", "warm", "in", "Paris."],
        interruption_type="topic-change"
    )
    assert res["strategy"] == "topic-change"
    history = load_history(session_id)
    assert len(history) == 1
    assert history[0]["role"] == "user"

    # 3. Test CLARIFICATION Strategy
    setup_base_history()
    res = resolve(
        session_id=session_id,
        spoken_words=["The", "weather", "is", "currently"],
        unspoken_words=["sunny", "and", "warm", "in", "Paris."],
        interruption_type="clarification"
    )
    assert res["strategy"] == "clarification"
    history = load_history(session_id)
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "The weather is currently"
    assert res["merged_context"]["unspoken_text"] == "sunny and warm in Paris."

    # 4. Test STOP_CANCEL Strategy
    setup_base_history()
    res = resolve(
        session_id=session_id,
        spoken_words=["The", "weather", "is", "currently"],
        unspoken_words=["sunny", "and", "warm", "in", "Paris."],
        interruption_type="stop_cancel"
    )
    assert res["strategy"] == "stop-cancel"
    history = load_history(session_id)
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "The weather is currently"

    # 5. Test ADD_ON Strategy
    setup_base_history()
    res = resolve(
        session_id=session_id,
        spoken_words=["The", "weather", "is", "currently"],
        unspoken_words=["sunny", "and", "warm", "in", "Paris."],
        interruption_type="add_on"
    )
    assert res["strategy"] == "add-on"
    history = load_history(session_id)
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "The weather is currently sunny and warm in Paris."
