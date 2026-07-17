import time
from common.config.settings import get_settings
from common.logging.logger import get_logger

logger = get_logger("primary-llm")

def call_primary(session_id: str, turn_id: str, messages: list[dict]) -> str:
    """Streams completions from Groq or mock fallback depending on configuration."""
    settings = get_settings()
    api_key = settings.groq_api_key
    
    start_time = time.time()
    
    # Return context-aware response if using dummy keys or test mode
    if not api_key or api_key == "dummy_val" or settings.env == "test":
        time.sleep(0.05)  # Simulate network hop latency
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
        # Mock answers for scripted multi-turn tests
        last_user_message = messages[-1]["content"].lower() if messages else ""
        if "mars" in last_user_message:
            return "Mars is the fourth planet from the Sun and the second-smallest planet in the Solar System."
        elif "far" in last_user_message or "distance" in last_user_message:
            # Asserts that context history is preserved and was retrieved
            context_has_mars = any("mars" in msg["content"].lower() for msg in messages[:-1])
            if context_has_mars:
                return "It is about 225 million kilometers away from Earth on average."
            else:
                return "Distance to what? Please specify the object."
        else:
            return "You're welcome!"

    # Real call using groq sdk
    from groq import Groq
    client = Groq(api_key=api_key)
    
    # Prepend standard system prompt to maintain persona
    payload = [
        {
            "role": "system",
            "content": "You are a helpful, concise voice assistant. Keep answers under 25 words."
        }
    ] + messages
    
    chat_completion = client.chat.completions.create(
        messages=payload,
        model=settings.groq_model,
        stream=True
    )
    
    collected_chunks = []
    first_token_fired = False
    for chunk in chat_completion:
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
    logger.log(
        event_name="llm_complete",
        session_id=session_id,
        turn_id=turn_id,
        latency_ms=total_latency_ms,
        detail={"provider": "groq"}
    )
    return full_text
