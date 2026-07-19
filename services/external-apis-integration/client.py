"""
client.py — Phase 6 external APIs integration mock client.
"""

import time
from common.logging.logger import get_logger

logger = get_logger("external-apis-integration")

class NetworkError(Exception):
    pass

class ProviderError(Exception):
    pass

class ValidationError(Exception):
    pass

def handle_api_request(tool_name: str, params: dict) -> dict:
    """
    Executes mock API requests with simulated latencies, errors, and validation.
    
    Logs external_api_called and external_api_failed events.
    """
    session_id = params.get("session_id", "system")
    tool_call_id = params.get("tool_call_id", "unknown")
    start_time = time.time()

    logger.log(
        event_name="external_api_called",
        session_id=session_id,
        turn_id="system",
        detail={"tool_name": tool_name, "tool_call_id": tool_call_id}
    )

    try:
        # Simulate network delay
        time.sleep(0.1)

        # Force error parameters for testing
        if params.get("force_error") == "ValidationError":
            raise ValidationError("Invalid request parameters.")
        elif params.get("force_error") == "NetworkError":
            raise NetworkError("Connection refused by provider host.")
        elif params.get("force_error") == "ProviderError":
            raise ProviderError("Upstream server returned HTTP 503 Service Unavailable.")
        elif params.get("force_error") == "Timeout":
            raise TimeoutError("Request timed out.")
        elif params.get("force_error") == "InternalError":
            raise RuntimeError("Unexpected internal system fault.")

        if tool_name == "check_balance":
            account_id = params.get("account_id")
            if not account_id:
                raise ValidationError("account_id is required.")
            result = {"status": "success", "balance": "$4,250.00", "account_id": account_id}
            
        elif tool_name == "transfer_funds":
            from_account = params.get("from_account")
            to_account = params.get("to_account")
            amount = params.get("amount")
            tx_token = params.get("tx_token") # For idempotency token tracking
            
            if not from_account or not to_account or not amount:
                raise ValidationError("from_account, to_account, and amount are required.")
            result = {
                "status": "success",
                "transaction_id": f"tx_{int(time.time())}",
                "amount": amount,
                "tx_token": tx_token
            }
            
        else:
            raise ValidationError(f"Unknown tool_name: {tool_name}")

        latency_ms = int((time.time() - start_time) * 1000)
        logger.log(
            event_name="external_api_completed",
            session_id=session_id,
            turn_id="system",
            detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "latency_ms": latency_ms}
        )
        return result

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.log(
            event_name="external_api_failed",
            session_id=session_id,
            turn_id="system",
            detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "reason": str(e), "latency_ms": latency_ms}
        )
        raise
