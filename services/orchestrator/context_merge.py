"""
context_merge.py — Phase 5 deliverable.
"""

from common.logging.logger import get_logger
from services.orchestrator.state_store import load_history, clear_session, save_turn

logger = get_logger("context-merge")

def resolve(session_id: str, spoken_words, unspoken_words, interruption_type: str) -> dict:
    """
    Decides the resolution strategy and merges the context for the next LLM call based
    on the spoken vs. unspoken words and classified interruption type.
    
    Args:
        session_id: The active session ID.
        spoken_words: List of word strings or a space-separated string of words spoken.
        unspoken_words: List of word strings or a space-separated string of unspoken words.
        interruption_type: The category of interruption (correction, topic-change, clarification, stop_cancel, add_on).
        
    Returns:
        dict: {
            "strategy": str,
            "merged_context": {
                "history": list,
                "spoken_text": str,
                "unspoken_text": str
            }
        }
    """
    # Normalize inputs
    if isinstance(spoken_words, list):
        spoken_text = " ".join(spoken_words).strip()
    else:
        spoken_text = str(spoken_words).strip()

    if isinstance(unspoken_words, list):
        unspoken_text = " ".join(unspoken_words).strip()
    else:
        unspoken_text = str(unspoken_words).strip()

    # Normalize interruption type
    norm_type = interruption_type.lower().replace("-", "_")

    history = load_history(session_id)
    updated_history = []
    
    # Locate last assistant message index
    last_assistant_idx = -1
    for i in range(len(history) - 1, -1, -1):
        if history[i]["role"] == "assistant":
            last_assistant_idx = i
            break

    strategy = norm_type.replace("_", "-") # Normalize strategy output to hyphenated

    if norm_type == "correction":
        # correction -> merge correction into context, regenerate response from corrected point.
        # Last assistant turn is truncated to only what was spoken.
        strategy = "correction"
        for idx, msg in enumerate(history):
            if idx == last_assistant_idx:
                if spoken_text:
                    updated_history.append({"role": "assistant", "content": spoken_text})
            else:
                updated_history.append(msg)
                
    elif norm_type in ("topic_change", "topic-change"):
        # topic-change -> abandon current response entirely, start fresh.
        # Last assistant turn is completely discarded from history.
        strategy = "topic-change"
        for idx, msg in enumerate(history):
            if idx != last_assistant_idx:
                updated_history.append(msg)
                
    elif norm_type == "clarification":
        # clarification -> pause, answer clarification, then resume original (unspoken).
        # Last assistant turn is truncated to spoken_text, unspoken is saved for resume.
        strategy = "clarification"
        for idx, msg in enumerate(history):
            if idx == last_assistant_idx:
                if spoken_text:
                    updated_history.append({"role": "assistant", "content": spoken_text})
            else:
                updated_history.append(msg)
                
    elif norm_type in ("stop_cancel", "stop-cancel"):
        # stop_cancel -> abandon response, no resume.
        # Last assistant turn is truncated to spoken_text or removed if empty.
        strategy = "stop-cancel"
        for idx, msg in enumerate(history):
            if idx == last_assistant_idx:
                if spoken_text:
                    updated_history.append({"role": "assistant", "content": spoken_text})
            else:
                updated_history.append(msg)
                
    elif norm_type in ("add_on", "add-on"):
        # add_on -> finish or fold the addition, continue naturally (keep full assistant text).
        strategy = "add-on"
        updated_history = history.copy()
        
    else:
        # Default fallback
        strategy = "topic-change"
        updated_history = history.copy()

    # Overwrite the updated history back into the database
    clear_session(session_id)
    for msg in updated_history:
        save_turn(session_id, "system", msg["role"], msg["content"])

    merged_context = {
        "history": updated_history,
        "spoken_text": spoken_text,
        "unspoken_text": unspoken_text
    }

    logger.log(
        event_name="interruption_resolved",
        session_id=session_id,
        turn_id="system",
        detail={
            "strategy": strategy,
            "merged_context_summary": f"history_len: {len(updated_history)}, unspoken: {unspoken_text[:30]}"
        }
    )

    return {
        "strategy": strategy,
        "merged_context": merged_context
    }
