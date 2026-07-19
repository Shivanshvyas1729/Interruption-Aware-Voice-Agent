import pytest
import time
from unittest.mock import patch
from services.orchestrator import cache_client
from common.config.voice_settings import get as vc_get

def test_cache_hit_and_miss_and_similarity():
    session_id = "session-cache-test"
    query = "What is the capital of France?"
    similar_query = "What is the capital of France indeed?"
    different_query = "What is the capital of Germany?"
    response = "The capital of France is Paris."
    
    system_prompt = "You are a helpful assistant."
    model_name = "test-model"
    messages = [{"role": "user", "content": query}]

    # Clear previous cache entries
    cache_client.cache_manager.store.store.clear()
    cache_client.cache_manager.store.access_order.clear()

    # 1. First request is a cache miss
    res = cache_client.lookup(session_id, "1", query, system_prompt, model_name, messages)
    assert res is None

    # Store result
    cache_client.store(session_id, query, response, system_prompt, model_name, messages)

    # 2. Similar query should cache hit (Jaccard similarity >= 0.8)
    res_similar = cache_client.lookup(session_id, "2", similar_query, system_prompt, model_name, messages)
    assert res_similar == response

    # 3. Different query should cache miss
    res_diff = cache_client.lookup(session_id, "3", different_query, system_prompt, model_name, messages)
    assert res_diff is None

def test_cache_ttl_expiration():
    session_id = "session-ttl-test"
    query = "Hello there"
    response = "Hi"
    system_prompt = "system"
    model_name = "model"
    messages = [{"role": "user", "content": query}]

    cache_client.cache_manager.store.store.clear()
    cache_client.cache_manager.store.access_order.clear()

    # Store entry
    cache_client.store(session_id, query, response, system_prompt, model_name, messages)

    # Verify hit
    assert cache_client.lookup(session_id, "1", query, system_prompt, model_name, messages) == response

    # Mock time to exceed TTL
    with patch("time.time", return_value=time.time() + 4000):
        assert cache_client.lookup(session_id, "2", query, system_prompt, model_name, messages) is None

def test_cache_eviction_lru():
    # Set max_size to 2
    store_instance = cache_client.InMemoryCacheStore(max_size=2)
    manager = cache_client.CacheManager(store_instance, cache_client._default_strategy)
    
    session_id = "session-evict-test"
    system_prompt = "system"
    model_name = "model"

    # Add 2 items
    manager.store_result(session_id, "query1", "resp1", system_prompt, model_name, [{"role": "user", "content": "query1"}])
    manager.store_result(session_id, "query2", "resp2", system_prompt, model_name, [{"role": "user", "content": "query2"}])

    # Touch query1 to update LRU order
    manager.lookup(session_id, "1", "query1", system_prompt, model_name, [{"role": "user", "content": "query1"}])

    # Add 3rd item, query2 should be evicted (least recently used)
    manager.store_result(session_id, "query3", "resp3", system_prompt, model_name, [{"role": "user", "content": "query3"}])

    assert manager.lookup(session_id, "2", "query1", system_prompt, model_name, [{"role": "user", "content": "query1"}]) == "resp1"
    assert manager.lookup(session_id, "3", "query2", system_prompt, model_name, [{"role": "user", "content": "query2"}]) is None
    assert manager.lookup(session_id, "4", "query3", system_prompt, model_name, [{"role": "user", "content": "query3"}]) == "resp3"

def test_cache_safety_isolation():
    session_id_1 = "session-user-1"
    session_id_2 = "session-user-2"
    query = "Sensitive info"
    response = "Secret 123"
    system_prompt = "system"
    model_name = "model"
    messages = [{"role": "user", "content": query}]

    cache_client.cache_manager.store.store.clear()
    cache_client.cache_manager.store.access_order.clear()

    # Store for session 1
    cache_client.store(session_id_1, query, response, system_prompt, model_name, messages)

    # Session 1 hits cache
    assert cache_client.lookup(session_id_1, "1", query, system_prompt, model_name, messages) == response
    # Session 2 misses cache (no leakage)
    assert cache_client.lookup(session_id_2, "2", query, system_prompt, model_name, messages) is None

def test_cache_tool_calling_compatibility():
    session_id = "session-tool-test"
    query = "Call a tool"
    response = "Tool output"
    system_prompt = "system"
    model_name = "model"

    # Messages contain tool call
    messages_with_tool = [
        {"role": "user", "content": query},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "tool_1"}]}
    ]

    cache_client.cache_manager.store.store.clear()

    # Attempt to lookup/store should do nothing
    res = cache_client.lookup(session_id, "1", query, system_prompt, model_name, messages_with_tool)
    assert res is None
    cache_client.store(session_id, query, response, system_prompt, model_name, messages_with_tool)
    
    # Verify not stored
    res_after = cache_client.lookup(session_id, "2", query, system_prompt, model_name, [{"role": "user", "content": query}])
    assert res_after is None
