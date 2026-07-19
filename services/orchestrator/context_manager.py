import time
import json
from typing import Any
from common.config.voice_settings import get as vc_get
from common.logging.logger import get_logger

logger = get_logger("context-manager")

# ---------------------------------------------------------------------------
# Token estimation (no external tokenizer dependency)
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    chars_per = vc_get("context.estimation.chars_per_token", 4)
    return max(1, len(text) // chars_per)


def estimate_message_tokens(msg: dict) -> int:
    overhead = vc_get("context.estimation.overhead_per_message", 3)
    role_cost = estimate_tokens(msg.get("role", ""))
    content_cost = estimate_tokens(msg.get("content", ""))
    return role_cost + content_cost + overhead


def estimate_history_tokens(messages: list[dict]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def deduplicate_messages(messages: list[dict]) -> list[dict]:
    cfg = vc_get("context.deduplication", {})
    if not cfg.get("enabled", True):
        return messages

    deduped: list[dict] = []
    seen_texts: set = set()

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "").strip()

        if not content:
            continue

        if cfg.get("consecutive_match", True) and deduped:
            last = deduped[-1]
            if last["role"] == role and last["content"] == content:
                continue

        if cfg.get("exact_match", True):
            key = f"{role}:{content}"
            if key in seen_texts:
                continue
            seen_texts.add(key)

        deduped.append(msg)

    saved = len(messages) - len(deduped)
    if saved:
        logger.log("context_dedup", "system", "system", detail={"removed": saved})
    return deduped


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------

def compress_message(msg: dict) -> dict:
    cfg = vc_get("context.compression", {})
    if not cfg.get("enabled", True):
        return msg

    content = msg.get("content", "")
    max_len = cfg.get("max_message_length", 200)

    if len(content) <= max_len:
        return msg

    stripped = content.rstrip(".,!? \t")
    return {"role": msg["role"], "content": stripped[:max_len].rstrip() + " [...]"}


def strip_filler(text: str) -> str:
    fillers = [
        "um ", "uh ", "like ", "you know ", "actually ", "basically ",
        "honestly ", "literally ", "i mean ", "so ", "well ", "right "
    ]
    lower = text.lower()
    for f in fillers:
        idx = lower.find(f)
        if idx == 0 or (idx > 0 and lower[idx - 1] in {" ", ".", ",", "!", "?"}):
            text = text[:idx] + text[idx + len(f):]
            lower = text.lower()
    return text.strip()


def compress_history(messages: list[dict]) -> list[dict]:
    cfg = vc_get("context.compression", {})
    if not cfg.get("enabled", True):
        return messages

    result = []
    for msg in messages:
        content = msg.get("content", "")
        if cfg.get("strip_filler", True):
            content = strip_filler(content)
        compressed = compress_message({"role": msg["role"], "content": content})
        result.append(compressed)
    return result


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------

def trim_history(messages: list[dict]) -> dict:
    """
    Apply sliding window and optional summarization.
    Returns {"messages": [...], "summary": str|None, "dropped": int, "summary_tokens": int}.
    """
    cfg = vc_get("context.sliding_window", {})
    summary_cfg = vc_get("context.summarization", {})
    budget_cfg = vc_get("context.token_budget", {})

    if not cfg.get("enabled", True):
        return {"messages": messages, "summary": None, "dropped": 0, "summary_tokens": 0}

    max_turns = cfg.get("max_turns", 10)
    max_messages = cfg.get("max_messages", 20)
    per_turn_budget = budget_cfg.get("per_turn", 2048)

    orig_count = len(messages)
    summary = None
    summary_tokens = 0

    if orig_count <= max_messages:
        if estimate_history_tokens(messages) <= per_turn_budget:
            return {"messages": messages, "summary": None, "dropped": 0, "summary_tokens": 0}

    # Build turn pairs
    turns = []
    i = 0
    while i < len(messages):
        user_msg = messages[i] if i < len(messages) and messages[i]["role"] == "user" else None
        asst_msg = messages[i + 1] if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant" else None
        if user_msg and asst_msg:
            turns.append((user_msg, asst_msg))
            i += 2
        elif user_msg:
            turns.append((user_msg, None))
            i += 1
        else:
            i += 1

    # If still over budget, summarize old turns
    if len(turns) > max_turns and summary_cfg.get("enabled", True):
        summarizable = turns[:-(max_turns - 1)] if max_turns > 1 else turns[:1]
        keep_turns = turns[-(max_turns - 1):] if max_turns > 1 else turns[-1:]

        seg_text = "\n".join(
            f"User: {u.get('content', '')}\nAssistant: {a.get('content', '') if a else ''}"
            for u, a in summarizable
        )
        summary = _summarize(seg_text)
        if summary:
            summary_tokens = estimate_tokens(summary)
            turns = keep_turns

    # Flatten turns back to message list
    result = []
    for u, a in turns:
        if u:
            result.append(u)
        if a:
            result.append(a)

    dropped = orig_count - len(result)
    if dropped > 0:
        logger.log("context_trimmed", "system", "system", detail={
            "original": orig_count, "after": len(result), "dropped": dropped,
            "summary": bool(summary), "summary_tokens": summary_tokens
        })

    return {"messages": result, "summary": summary, "dropped": dropped, "summary_tokens": summary_tokens}


def _summarize(segment_text: str) -> str | None:
    summary_cfg = vc_get("context.summarization", {})
    if not summary_cfg.get("enabled", True):
        return None

    from common.config.settings import get_settings
    settings = get_settings()
    api_key = settings.groq_api_key

    if not api_key or api_key == "dummy_val" or settings.env == "test":
        word_count = len(segment_text.split())
        return f"Previous conversation segment ({word_count} words)."

    from groq import Groq
    client = Groq(api_key=api_key)
    system_prompt = summary_cfg.get("summary_prompt",
        "Summarize the key points from this conversation segment concisely in 1-2 sentences.")
    model = summary_cfg.get("summary_model", "llama-3.1-8b-instant")

    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": segment_text}
            ],
            model=model,
            temperature=0.3,
            max_tokens=150
        )
        summary = completion.choices[0].message.content.strip()
        logger.log("context_summary", "system", "system",
                   detail={"summary_len": len(summary), "model": model})
        return summary
    except Exception as e:
        logger.log("context_summary_failed", "system", "system",
                   detail={"error": str(e)})
        word_count = len(segment_text.split())
        return f"Previous conversation segment ({word_count} words)."


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------

class TokenBudget:
    def __init__(self, session_id: str):
        self.session_id = session_id
        cfg = vc_get("context.token_budget", {})
        self.per_session = cfg.get("per_session", 16384)
        self.warn_at = cfg.get("warn_at", 0.8)
        self.hard_limit = cfg.get("hard_limit", True)
        self.prompt_tokens = 0
        self.completion_tokens = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def usage_pct(self) -> float:
        return round(self.total / max(self.per_session, 1) * 100, 1)

    def record_prompt(self, tokens: int):
        self.prompt_tokens += tokens
        if self.total > self.per_session * self.warn_at:
            logger.log("token_budget_warning", self.session_id, "system",
                       detail={"total": self.total, "budget": self.per_session,
                               "pct": self.usage_pct})

    def record_completion(self, tokens: int):
        self.completion_tokens += tokens

    def within_budget(self, extra_prompt_tokens: int = 0) -> bool:
        if not self.hard_limit:
            return True
        return (self.total + extra_prompt_tokens) < self.per_session

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total": self.total,
            "budget": self.per_session,
            "usage_pct": self.usage_pct
        }


_budgets: dict[str, TokenBudget] = {}


def get_token_budget(session_id: str) -> TokenBudget:
    if session_id not in _budgets:
        _budgets[session_id] = TokenBudget(session_id)
    return _budgets[session_id]


def reset_token_budget(session_id: str):
    _budgets.pop(session_id, None)


# ---------------------------------------------------------------------------
# Full pipeline: dedup -> compress -> trim -> inject summary
# ---------------------------------------------------------------------------

def prepare_context(history: list[dict], session_id: str = "") -> list[dict]:
    budget = get_token_budget(session_id) if session_id else None
    if budget and not budget.within_budget():
        logger.log("token_budget_exceeded", session_id, "system",
                   detail=budget.to_dict())
        # Return only last 2 messages if over budget
        return history[-2:]

    result = deduplicate_messages(history)
    result = compress_history(result)
    trimmed = trim_history(result)

    messages = trimmed["messages"]
    summary = trimmed["summary"]

    if summary:
        messages.insert(0, {"role": "system", "content": f"[Conversation Summary] {summary}"})

    prompt_tokens = estimate_history_tokens(messages)
    if budget:
        budget.record_prompt(prompt_tokens)

    return messages
