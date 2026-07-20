import pytest
import os
import sys
import asyncio
from unittest.mock import MagicMock, patch

# Pre-emptively mock the openai module in sys.modules to allow offline testing
mock_openai = MagicMock()
sys.modules["openai"] = mock_openai

from common.config.settings import get_settings
from services.orchestrator.state_store import save_turn, get_redis_client, _memory_db
from services.orchestrator.async_pipeline import LLMWorker, LLMRequest

def test_redis_fail_fast_in_production():
    settings = get_settings()
    # Save original env
    orig_env = settings.env
    try:
        # Mock redis.from_url to raise a connection error
        with patch("redis.from_url") as mock_from_url:
            import redis
            mock_client = MagicMock()
            mock_client.ping.side_effect = redis.ConnectionError("Redis connection refused")
            mock_from_url.return_value = mock_client
            
            # Reset cached client
            import services.orchestrator.state_store
            services.orchestrator.state_store._redis_client = None
            
            # In test mode, it should log and return None (fallback to memory)
            settings.env = "test"
            client = get_redis_client()
            assert client is None
            
            # In production mode, it should raise ConnectionError
            settings.env = "production"
            services.orchestrator.state_store._redis_client = None
            with pytest.raises(redis.ConnectionError):
                get_redis_client()
    finally:
        settings.env = orig_env
        services.orchestrator.state_store._redis_client = None

def test_llm_worker_failover_to_openai():
    async def run_test():
        # Test that LLMWorker falls back to OpenAI if Groq fails
        settings = get_settings()
        orig_env = settings.env
        orig_groq = settings.groq_api_key
        orig_openai = settings.openai_api_key
        
        settings.env = "production"
        settings.groq_api_key = "mock-groq-key"
        settings.openai_api_key = "mock-openai-key"
        
        worker = LLMWorker()
        worker.input = asyncio.Queue()
        worker.output = asyncio.Queue()
        
        req = LLMRequest(
            messages=[{"role": "user", "content": "Hello"}],
            session_id="test-session-failover",
            turn_id=1
        )
        await worker.input.put(req)
        
        # Mock Groq to raise exception and OpenAI to succeed
        mock_groq_instance = MagicMock()
        # When creating completion on Groq, raise error
        mock_groq_instance.chat.completions.create.side_effect = Exception("Groq Rate Limit")
        
        mock_openai_instance = MagicMock()
        mock_chunk = MagicMock()
        mock_choice = MagicMock()
        mock_choice.delta.content = "OpenAI response"
        mock_choice.message.content = "OpenAI response"
        mock_chunk.choices = [mock_choice]
        
        # Support both stream=False (returns object with choices) and stream=True (iterable list of chunks)
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.__iter__.return_value = [mock_chunk]
        mock_openai_instance.chat.completions.create.return_value = mock_response
        
        # Configure our mocked module's class return value
        mock_openai.OpenAI.return_value = mock_openai_instance
        
        # We also mock telemetry_bus.push to verify events
        from services.edge_auth.telemetry_bus import telemetry_bus
        
        with patch("groq.Groq", return_value=mock_groq_instance), \
             patch.object(telemetry_bus, "push") as mock_push:
             
            # Start worker as task
            task = asyncio.create_task(worker.run())
            # Wait a bit for processing
            await asyncio.sleep(0.1)
            # Cancel worker
            await worker.stop()
            
            # Verify LLMResponse output
            assert not worker.output.empty()
            res = await worker.output.get()
            assert "OpenAI response" in res.text
            
            # Verify that failover telemetry event was pushed
            failover_pushed = any(call[0][0] == "llm_failover_triggered" for call in mock_push.call_args_list)
            assert failover_pushed
            
        # Restore settings
        settings.env = orig_env
        settings.groq_api_key = orig_groq
        settings.openai_api_key = orig_openai

    asyncio.run(run_test())
