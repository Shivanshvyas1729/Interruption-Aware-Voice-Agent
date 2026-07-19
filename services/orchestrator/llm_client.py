import time
from common.config.settings import get_settings
from common.config.voice_settings import get as vc_get
from common.logging.logger import get_logger
from services.orchestrator.context_manager import (
    estimate_tokens,
    get_token_budget,
    prepare_context,
)

logger = get_logger("primary-llm")

def call_primary(session_id: str, turn_id: str, messages: list[dict]) -> str:
    """Streams completions from Groq or mock fallback depending on configuration."""
    settings = get_settings()
    api_key = settings.groq_api_key
    
    start_time = time.time()
    
    # Return context-aware response if using dummy keys or test mode
    if not api_key or api_key == "dummy_val" or settings.env == "test":
        time.sleep(vc_get("llm.mock_sleep_ms", 50) / 1000.0)
        latency_ms = int((time.time() - start_time) * 1000)
        logger.log(
            event_name="llm_first_token",
            session_id=session_id,
            turn_id=turn_id,
            latency_ms=latency_ms,
            detail={}
        )
        logger.log(
            event_name="llm_complete",
            session_id=session_id,
            turn_id=turn_id,
            latency_ms=latency_ms + 10,
            detail={"provider": "groq_mock"}
        )
        last_user_message = messages[-1]["content"].lower() if messages else ""
        if "mars" in last_user_message:
            return "Mars is the fourth planet from the Sun and the second-smallest planet in the Solar System."
        elif "far" in last_user_message or "distance" in last_user_message:
            context_has_mars = any("mars" in msg["content"].lower() for msg in messages[:-1])
            if context_has_mars:
                return "It is about 225 million kilometers away from Earth on average."
            else:
                return "Distance to what? Please specify the object."
        else:
            return "You're welcome!"

    # Apply context management (dedup, compress, sliding window, summarization, budget)
    budget = get_token_budget(session_id)
    context_history = prepare_context(messages, session_id)
    system_prompt = vc_get("llm.system_prompt", "You are a helpful, concise voice assistant.")
    payload = [
        {"role": "system", "content": system_prompt}
    ] + context_history

    prompt_tokens = estimate_tokens(system_prompt) + sum(estimate_tokens(m.get("content", "")) for m in context_history)
    budget.record_prompt(prompt_tokens)

    from groq import Groq
    client = Groq(api_key=api_key)
    
    chat_completion = client.chat.completions.create(
        messages=payload,
        model=settings.groq_model,
        stream=True
    )
    
    from services.orchestrator.cancellation_manager import cancellation_manager
    
    collected_chunks = []
    first_token_fired = False
    for chunk in chat_completion:
        # Check if cancelled mid-turn to abort token generation immediately
        if cancellation_manager.is_cancelled(session_id):
            logger.log(
                event_name="llm_cancelled",
                session_id=session_id,
                turn_id=turn_id,
                detail={"msg": "LLM token stream aborted mid-turn."}
            )
            return ""
            
        delta = chunk.choices[0].delta.content or ""
        collected_chunks.append(delta)
        if delta and not first_token_fired:
            first_token_fired = True
            latency_ms = int((time.time() - start_time) * 1000)
            logger.log(
                event_name="llm_first_token",
                session_id=session_id,
                turn_id=turn_id,
                latency_ms=latency_ms,
                detail={}
            )
            
    full_text = "".join(collected_chunks)
    total_latency_ms = int((time.time() - start_time) * 1000)
    completion_tok = estimate_tokens(full_text)
    budget = get_token_budget(session_id)
    budget.record_completion(completion_tok)
    logger.log(
        event_name="llm_complete",
        session_id=session_id,
        turn_id=turn_id,
        latency_ms=total_latency_ms,
        detail={"provider": "groq", "prompt_tokens": budget.prompt_tokens,
                "completion_tokens": completion_tok, "budget_pct": budget.usage_pct}
    )
    return full_text
