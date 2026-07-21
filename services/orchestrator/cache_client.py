import time
import re
import hashlib
import threading
from typing import Dict, List, Optional, Any
from common.logging.logger import get_logger
from common.config.voice_settings import get as vc_get

logger = get_logger("llm-semantic-cache")

class CacheStrategy:
    def calculate_similarity(self, query1: str, query2: str) -> float:
        raise NotImplementedError

class JaccardSimilarityStrategy(CacheStrategy):
    def __init__(self, threshold: float = 0.8):
        self.threshold = threshold

    def _get_tokens(self, text: str) -> set:
        return set(re.findall(r'\w+', text.lower()))

    def calculate_similarity(self, query1: str, query2: str) -> float:
        tokens1 = self._get_tokens(query1)
        tokens2 = self._get_tokens(query2)
        if not tokens1 or not tokens2:
            return 0.0
        # Require exact match if either query is short (< 4 tokens) to avoid false hits
        if len(tokens1) < 4 or len(tokens2) < 4:
            return 1.0 if tokens1 == tokens2 else 0.0
        return len(tokens1.intersection(tokens2)) / len(tokens1.union(tokens2))

class CacheStore:
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def set(self, key: str, value: Dict[str, Any], ttl: float) -> None:
        raise NotImplementedError

class InMemoryCacheStore(CacheStore):
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.store: Dict[str, Dict[str, Any]] = {}
        # Track access order for LRU eviction: list of keys, front is least recently used
        self.access_order: List[str] = []
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            if key in self.store:
                entry = self.store[key]
                # Check TTL expiration
                if time.time() > entry["expires_at"]:
                    self._evict(key)
                    return None
                # Update LRU order
                if key in self.access_order:
                    self.access_order.remove(key)
                self.access_order.append(key)
                return entry["value"]
            return None

    def set(self, key: str, value: Dict[str, Any], ttl: float) -> None:
        with self.lock:
            # Evict if max_size exceeded
            if len(self.store) >= self.max_size and key not in self.store:
                if self.access_order:
                    lru_key = self.access_order.pop(0)
                    self._evict(lru_key)
                    logger.log(
                        event_name="cache_eviction",
                        session_id="system",
                        turn_id="system",
                        detail={"evicted_key": lru_key, "reason": "LRU max_size limit reached"}
                    )

            expires_at = time.time() + ttl
            self.store[key] = {"value": value, "expires_at": expires_at}
            if key in self.access_order:
                self.access_order.remove(key)
            self.access_order.append(key)

    def _evict(self, key: str) -> None:
        if key in self.store:
            del self.store[key]
        if key in self.access_order:
            self.access_order.remove(key)

class StampedeProtection:
    def __init__(self):
        self._events: Dict[str, threading.Event] = {}
        self._results: Dict[str, Any] = {}
        self.lock = threading.Lock()

    def check_or_wait(self, cache_key: str, turn_id: str, session_id: str) -> Optional[str]:
        event = None
        with self.lock:
            if cache_key in self._events:
                event = self._events[cache_key]
            else:
                return None
        
        if event:
            logger.log(
                event_name="stampede_protection_triggered",
                session_id=session_id,
                turn_id=turn_id,
                detail={"cache_key": cache_key}
            )
            # Wait for the event to fire
            event.wait(timeout=10.0)
            with self.lock:
                return self._results.get(cache_key)
        return None

    def start_fetch(self, cache_key: str) -> None:
        with self.lock:
            if cache_key in self._results:
                del self._results[cache_key]
            if cache_key not in self._events:
                self._events[cache_key] = threading.Event()

    def end_fetch(self, cache_key: str, result: str) -> None:
        with self.lock:
            self._results[cache_key] = result
            if cache_key in self._events:
                self._events[cache_key].set()
                # Clean up event
                del self._events[cache_key]

    def cancel_fetch(self, cache_key: str) -> None:
        with self.lock:
            if cache_key in self._events:
                self._events[cache_key].set()
                del self._events[cache_key]

class CacheManager:
    def __init__(self, store: CacheStore, strategy: CacheStrategy):
        self.store = store
        self.strategy = strategy
        self.stampede = StampedeProtection()

    def _generate_cache_key(self, session_id: str, system_prompt: str, model_name: str, context_history: list) -> str:
        """Generate a cache key that incorporates versioning for system prompt, prompt template, and output format.
        The key includes hashes of:
        - session identifier
        - system prompt content
        - model name
        - recent conversation history (last two turns)
        - optional version strings from voice settings for prompt/template/output format
        This ensures cache entries are invalidated automatically when any of these components change.
        """
        recent_history = context_history[-3:-1] if len(context_history) > 2 else context_history[:-1]
        hist_str = f"len:{len(context_history)}:" + str(recent_history)
        sys_hash = hashlib.md5(system_prompt.encode('utf-8')).hexdigest()
        model_hash = hashlib.md5(model_name.encode('utf-8')).hexdigest()
        hist_hash = hashlib.md5(hist_str.encode('utf-8')).hexdigest()
        # Additional version strings (default to empty if not set)
        prompt_version = vc_get("cache.prompt_template_version", "")
        system_prompt_version = vc_get("cache.system_prompt_version", "")
        output_format_version = vc_get("cache.output_format_version", "")
        version_hash = hashlib.md5((prompt_version + system_prompt_version + output_format_version).encode('utf-8')).hexdigest()
        return f"cache:{session_id}:{sys_hash}:{model_hash}:{hist_hash}:{version_hash}"

    def is_cache_safe(self, messages: list) -> bool:
        # Do not cache if any messages contain tool calls/results
        for msg in messages:
            if msg.get("role") == "tool" or "tool_calls" in msg:
                return False
        return True

    def lookup(self, session_id: str, turn_id: str, query: str, system_prompt: str, model_name: str, messages: list) -> Optional[str]:
        if not self.is_cache_safe(messages) or len(query.strip().split()) < 3:
            return None

        cache_key = self._generate_cache_key(session_id, system_prompt, model_name, messages)
        
        # 1. Check Stampede Protection first
        stampede_res = self.stampede.check_or_wait(cache_key, turn_id, session_id)
        if stampede_res:
            return stampede_res

        start_time = time.time()
        
        # 2. Lookup in store
        entries = self.store.get(cache_key) or []
        threshold = vc_get("cache.similarity_threshold", 0.8)
        
        for idx, entry in enumerate(entries):
            if time.time() > entry.get("expires_at", 0):
                continue
            # Enforce strict session_id match to prevent cross-session leaks
            if entry.get("session_id") and entry.get("session_id") != session_id:
                continue
            
            similarity = self.strategy.calculate_similarity(query, entry["query"])
            if similarity >= threshold:
                # Update LRU order for this sub-entry within the partition: move it to the end
                hit_entry = entries.pop(idx)
                entries.append(hit_entry)
                self.store.set(cache_key, entries, vc_get("cache.ttl", 3600.0))

                latency_ms = int((time.time() - start_time) * 1000)
                logger.log(
                    event_name="cache_hit",
                    session_id=session_id,
                    turn_id=turn_id,
                    latency_ms=latency_ms,
                    detail={"query": query, "cached_query": entry["query"], "similarity": similarity}
                )
                return entry["response"]

        # Cache miss: register as fetching for stampede protection
        self.stampede.start_fetch(cache_key)
        
        logger.log(
            event_name="cache_miss",
            session_id=session_id,
            turn_id=turn_id,
            detail={"query": query}
        )
        return None

    def store_result(self, session_id: str, query: str, response: str, system_prompt: str, model_name: str, messages: list) -> None:
        if not self.is_cache_safe(messages) or not query or not response:
            return

        cache_key = self._generate_cache_key(session_id, system_prompt, model_name, messages)
        
        # Signal stampede protection that fetching is done
        self.stampede.end_fetch(cache_key, response)

        default_ttl = vc_get("cache.ttl", 3600.0)
        entries = self.store.get(cache_key) or []
        
        # Filter out expired sub-entries
        entries = [e for e in entries if time.time() <= e.get("expires_at", 0)]
        # Remove exact duplicate if present
        entries = [e for e in entries if e["query"].lower().strip() != query.lower().strip()]
        
        # Enforce max size of sub-entries to prevent unbounded memory growth
        max_size = getattr(self.store, 'max_size', 100)
        if len(entries) >= max_size:
            logger.log(
                event_name="cache_eviction",
                session_id=session_id,
                turn_id="system",
                detail={"reason": "max_size limit reached for partition"}
            )
            entries.pop(0)

        expires_at = time.time() + default_ttl
        entries.append({
            "session_id": session_id,
            "query": query,
            "response": response,
            "expires_at": expires_at
        })
        
        self.store.set(cache_key, entries, default_ttl)
        logger.log(
            event_name="cache_store",
            session_id=session_id,
            turn_id="system",
            detail={"query": query}
        )

    def clear_session_cache(self, session_id: str) -> None:
        """Purge all cached entries partition-keyed for a specific session."""
        if hasattr(self.store, 'lock') and hasattr(self.store, 'store'):
            with self.store.lock:
                prefix = f"cache:{session_id}:"
                keys_to_del = [k for k in self.store.store.keys() if k.startswith(prefix)]
                for k in keys_to_del:
                    self.store._evict(k)
                logger.log(
                    event_name="cache_session_cleared",
                    session_id=session_id,
                    turn_id="system",
                    detail={"cleared_keys": len(keys_to_del)}
                )

# Global singleton instances
_default_strategy = JaccardSimilarityStrategy(threshold=0.8)
_default_store = InMemoryCacheStore(max_size=100)
cache_manager = CacheManager(_default_store, _default_strategy)

def lookup(session_id: str, turn_id: str, query: str, system_prompt: str = "", model_name: str = "", messages: list = None) -> Optional[str]:
    msgs = messages or []
    return cache_manager.lookup(session_id, turn_id, query, system_prompt, model_name, msgs)

def store(session_id: str, query: str, response: str, system_prompt: str = "", model_name: str = "", messages: list = None) -> None:
    msgs = messages or []
    cache_manager.store_result(session_id, query, response, system_prompt, model_name, msgs)

def clear_session_cache(session_id: str) -> None:
    cache_manager.clear_session_cache(session_id)
