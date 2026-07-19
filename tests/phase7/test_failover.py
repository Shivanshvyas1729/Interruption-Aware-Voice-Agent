import pytest
import time
import sys
from unittest.mock import patch, MagicMock

# Mock openai module if it is not installed
sys.modules["openai"] = MagicMock()

from services.orchestrator import failover
from common.config.settings import get_settings

def test_successful_primary_call_no_failover():
    session_id = "session-failover-test"
    turn_id = "1"
    messages = [{"role": "user", "content": "Hello"}]

    failover.primary_circuit_breaker.record_success()

    with patch("services.orchestrator.llm_client.call_primary_direct", return_value="Groq response") as mock_primary, \
         patch("services.orchestrator.failover._call_fallback") as mock_fallback:
        
        res = failover.call_with_failover(session_id, turn_id, messages)
        assert res == "Groq response"
        mock_primary.assert_called_once_with(session_id, turn_id, messages)
        mock_fallback.assert_not_called()

def test_primary_failure_triggers_failover():
    session_id = "session-failover-test"
    turn_id = "2"
    messages = [{"role": "user", "content": "Hello"}]

    failover.primary_circuit_breaker.record_success()

    with patch("services.orchestrator.llm_client.call_primary_direct", side_effect=Exception("Timeout Error")), \
         patch("services.orchestrator.failover._call_fallback", return_value="OpenAI fallback response") as mock_fallback:
        
        res = failover.call_with_failover(session_id, turn_id, messages)
        assert res == "OpenAI fallback response"
        mock_fallback.assert_called_once_with(session_id, turn_id, messages)

def test_circuit_breaker_cooldown_and_recovery():
    session_id = "session-circuit-breaker-test"
    turn_id = "3"
    messages = [{"role": "user", "content": "Hello"}]

    # Reset circuit breaker
    failover.primary_circuit_breaker.consecutive_failures = 0
    failover.primary_circuit_breaker.cooldown_until = 0.0

    with patch("services.orchestrator.llm_client.call_primary_direct", side_effect=Exception("Failed API call")), \
         patch("services.orchestrator.failover._call_fallback", return_value="Fallback Response"):
        
        # 1. Trigger 3 consecutive failures to open the circuit breaker
        failover.call_with_failover(session_id, turn_id, messages)
        failover.call_with_failover(session_id, turn_id, messages)
        assert failover.primary_circuit_breaker.is_open() is False
        
        failover.call_with_failover(session_id, turn_id, messages)
        assert failover.primary_circuit_breaker.is_open() is True

        # 2. When circuit breaker is open, primary is NOT called (bypassed)
        with patch("services.orchestrator.llm_client.call_primary_direct") as mock_primary:
            res = failover.call_with_failover(session_id, turn_id, messages)
            assert res == "Fallback Response"
            mock_primary.assert_not_called()

        # 3. Simulate cooldown expiration (time moves forward by 61 seconds)
        with patch("time.time", return_value=time.time() + 65):
            assert failover.primary_circuit_breaker.is_open() is False
            
            # The next call should try the primary again
            with patch("services.orchestrator.llm_client.call_primary_direct", return_value="Groq recovered response") as mock_primary_rec:
                res = failover.call_with_failover(session_id, turn_id, messages)
                assert res == "Groq recovered response"
                mock_primary_rec.assert_called_once()

def test_both_providers_failing():
    session_id = "session-both-fail-test"
    turn_id = "4"
    messages = [{"role": "user", "content": "Hello"}]

    failover.primary_circuit_breaker.record_success()

    with patch("services.orchestrator.llm_client.call_primary_direct", side_effect=Exception("Primary Down")), \
         patch("openai.OpenAI") as mock_openai:
         
        # Make both fail
        mock_openai_instance = MagicMock()
        mock_openai_instance.chat.completions.create.side_effect = Exception("Fallback Down")
        mock_openai.return_value = mock_openai_instance
        
        # Force a real OpenAI call if fallback key is present, mock it otherwise
        with patch("services.orchestrator.failover.get_settings") as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.openai_api_key = "real-key-mock"
            mock_settings.return_value = mock_settings_instance
            
            with pytest.raises(RuntimeError) as exc_info:
                failover.call_with_failover(session_id, turn_id, messages)
            
            assert "service is temporarily unavailable" in str(exc_info.value)

