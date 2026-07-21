from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import json
import traceback
from pydantic import BaseModel
from services.edge_auth.consent_service import check_consent
from services.edge_auth.token_service import issue_token
from common.logging.logger import get_logger
from common.config.voice_settings import get_voice_config, get as vc_get
from services.edge_auth.telemetry_bus import telemetry_bus
from services.orchestrator.context_manager import prepare_context, get_token_budget, reset_token_budget
from services.orchestrator.async_pipeline import get_pipeline, get_cancel_token, shutdown_pipeline

logger = get_logger("api-gateway")
app = FastAPI(title="API Gateway")

# Log service startup
logger.log_service_start("api-gateway", detail={"port": vc_get("ports.api_gateway", 8003)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AuthRequest(BaseModel):
    session_id: str
    room_name: str

@app.post("/auth")
async def auth_route(req: AuthRequest):
    """Receive authentication requests, check consent, issue room token."""
    logger.log(
        event_name="auth_request_received",
        session_id=req.session_id,
        turn_id="system",
        detail={"room_name": req.room_name}
    )
    
    # Check user consent
    consent_approved = check_consent(req.session_id)
    if not consent_approved:
        logger.log(
            event_name="auth_request_routed",
            session_id=req.session_id,
            turn_id="system",
            detail={"outcome": "consent_denied"}
        )
        raise HTTPException(status_code=403, detail="Consent denied")
        
    # Issue LiveKit room token
    try:
        token = issue_token(req.session_id, req.room_name)
        logger.log(
            event_name="auth_request_routed",
            session_id=req.session_id,
            turn_id="system",
            detail={"outcome": "success"}
        )
        from common.config.settings import get_settings
        settings = get_settings()
        
        # Check active providers based on configured API keys in settings
        llm_prov = "Groq" if (settings.groq_api_key and settings.groq_api_key != "dummy_val") else "Mock LLM"
        tts_prov = "Cartesia" if (settings.cartesia_api_key and settings.cartesia_api_key != "dummy_val") else "Mock TTS"
        stt_prov = "Deepgram" if (settings.deepgram_api_key and settings.deepgram_api_key != "dummy_val") else "Mock STT"
        
        return {
            "token": token,
            "livekit_url": settings.livekit_url,
            "llm_provider": llm_prov,
            "llm_model": settings.groq_model,
            "tts_provider": tts_prov,
            "stt_provider": stt_prov
        }
    except Exception as e:
        logger.log(
            event_name="auth_request_routed",
            session_id=req.session_id,
            turn_id="system",
            detail={"outcome": f"failed: {str(e)}"}
        )
        raise HTTPException(status_code=500, detail=str(e))

class ChatRequest(BaseModel):
    session_id: str
    text: str

@app.post("/chat")
async def chat_route(req: ChatRequest):
    """Fallback text chat endpoint. Simulates turn processing, LLM, and TTS playback."""
    import base64
    import time
    import os
    import traceback
    
    print(f"\n[/chat] === REQUEST RECEIVED | session={req.session_id} | text={req.text!r} ===")
    
    try:
        # 1. Access the session FSM, reset cancellation state, and dispatch transcript
        from services.orchestrator.cancellation_manager import cancellation_manager
        cancellation_manager.reset_session(req.session_id)
        
        from services.orchestrator.fsm import get_fsm_for_session
        fsm = get_fsm_for_session(req.session_id)
        print(f"[/chat] FSM state before turn: {fsm.state}, turn_id={fsm.turn_id}")
        
        chat_start = time.time()
        telemetry_bus.push("stt_final", {"text": req.text, "session_id": req.session_id}, req.session_id, str(fsm.turn_id + 1))
        
        print(f"[/chat] Calling fsm.receive_transcript...")
        reply_text, audio_bytes = fsm.receive_transcript(req.text)
        print(f"[/chat] fsm.receive_transcript returned: reply={reply_text!r}, audio_bytes={len(audio_bytes) if audio_bytes else 0} bytes")
        
        budget = get_token_budget(req.session_id)
        if reply_text is None:
            print(f"[/chat] Turn was cancelled (reply_text is None), FSM state={fsm.state}")
            telemetry_bus.push("cancellation", {"reason": "turn_cancelled", "fsm_state": fsm.state}, req.session_id, str(fsm.turn_id))
            return {
                "reply": "",
                "reply_text": "",
                "audio": "",
                "audio_b64": "",
                "fsm_state": fsm.state,
                "tts_error": None,
                "total_latency": fsm.last_total_latency,
                "llm_latency": fsm.last_llm_latency,
                "tts_latency": fsm.last_tts_latency,
                "fsm": {
                    "session_id": fsm.session_id,
                    "state": fsm.state,
                    "turn_id": fsm.turn_id,
                    "confidence_threshold": getattr(fsm, "confidence_threshold", 0.6)
                },
                "token_budget": budget.to_dict()
            }
        
        telemetry_bus.push("llm_complete", {"latency_ms": fsm.last_llm_latency}, req.session_id, str(fsm.turn_id))
        telemetry_bus.push("tts_complete", {"latency_ms": fsm.last_tts_latency}, req.session_id, str(fsm.turn_id))
        telemetry_bus.push("turn_complete", {"total_latency_ms": fsm.last_total_latency}, req.session_id, str(fsm.turn_id))
        
        # 3. Base64 encode the synthesized audio safely
        audio_b64 = ""
        tts_error = None
        if audio_bytes:
            try:
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                print(f"[/chat] Audio encoded to base64: {len(audio_b64)} chars (original {len(audio_bytes)} bytes)")
            except Exception as tts_ex:
                print("\n=== TTS ENCODING FAILED ===")
                traceback.print_exc()
                print("============================\n")
                tts_error = str(tts_ex)
        else:
            print(f"[/chat] WARNING: audio_bytes is empty! TTS may have failed.")
                
        # 4. Log details to local file
        os.makedirs("logs", exist_ok=True)
        with open("logs/chat_history.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Session: {req.session_id} Turn: {fsm.turn_id}\n")
            f.write(f"  User: {req.text}\n")
            f.write(f"  Agent: {reply_text}\n")
            f.write(f"  LLM latency: {fsm.last_llm_latency}ms | TTS latency: {fsm.last_tts_latency}ms | Total: {fsm.last_total_latency}ms\n")
            f.write(f"  Audio bytes: {len(audio_bytes) if audio_bytes else 0}\n")
            if tts_error:
                f.write(f"  TTS Error: {tts_error}\n")
            f.write("\n")
            
        # Update metrics history
        _metrics_history["llm"].append(fsm.last_llm_latency)
        _metrics_history["tts"].append(fsm.last_tts_latency)
        _metrics_history["total"].append(fsm.last_total_latency)
        
        budget = get_token_budget(req.session_id)
        p_tok = budget.prompt_tokens
        c_tok = budget.completion_tokens
        _token_metrics["prompt_tokens"] = p_tok
        _token_metrics["completion_tokens"] = c_tok
        _token_metrics["total_tokens"] = p_tok + c_tok
        input_cost = vc_get("cost.input_cost_per_million", 0.59)
        output_cost = vc_get("cost.output_cost_per_million", 0.79)
        _token_metrics["cost"] = round((p_tok * input_cost + c_tok * output_cost) / 1000000, 6)
        
        telemetry_bus.push("token_usage", {
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "total_tokens": p_tok + c_tok,
            "cumulative_prompt": p_tok,
            "cumulative_completion": c_tok,
            "cumulative_cost": _token_metrics["cost"],
            "budget_pct": budget.usage_pct
        }, req.session_id, str(fsm.turn_id))
        
        print(f"[/chat] === RESPONSE READY | reply={reply_text!r} | audio_b64_len={len(audio_b64)} | tts_error={tts_error} ===\n")
            
        return {
            "reply": reply_text,
            "reply_text": reply_text,
            "audio": audio_b64,
            "audio_b64": audio_b64,
            "fsm_state": fsm.state,
            "tts_error": tts_error,
            "total_latency": fsm.last_total_latency,
            "llm_latency": fsm.last_llm_latency,
            "tts_latency": fsm.last_tts_latency,
            "fsm": {
                "session_id": fsm.session_id,
                "state": fsm.state,
                "turn_id": fsm.turn_id,
                "confidence_threshold": getattr(fsm, "confidence_threshold", 0.6)
            },
            "token_budget": budget.to_dict()
        }
    except Exception as e:
        print("\n=== EXCEPTION IN CHAT ROUTE ===")
        traceback.print_exc()
        print("===============================\n")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")

# Metrics history tracking dictionary
_metrics_history = {
    "llm": [],
    "tts": [],
    "total": []
}

def calculate_percentile(values, percentile):
    if not values:
        return 0
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * percentile / 100
    lower = sorted_values[int(index)]
    upper = sorted_values[min(int(index) + 1, len(sorted_values) - 1)]
    return int(lower + (upper - lower) * (index - int(index)))

def get_resource_usage():
    import time
    import os
    import subprocess
    
    sleep_ms = vc_get("resource_usage.sleep_ms", 5)
    start_cpu = time.process_time()
    start_real = time.perf_counter()
    time.sleep(sleep_ms / 1000.0)
    cpu = round((time.process_time() - start_cpu) / max((time.perf_counter() - start_real), 0.0001) * 100, 1)
    
    ram = 0
    try:
        pid = os.getpid()
        output = subprocess.check_output(f'tasklist /FI "PID eq {pid}" /NH /FO CSV', shell=True).decode('utf-8')
        parts = output.split(",")
        if len(parts) >= 5:
            ram_str = parts[4].replace('"', '').replace(' K', '').replace(',', '').strip()
            ram = round(int(ram_str) / 1024, 1)
    except Exception:
        ram = 35.5
        
    return {"cpu": cpu, "ram": ram}

def get_services_health():
    import requests
    from services.orchestrator.state_store import get_redis_client
    
    # 1. Redis Check
    redis_health = "healthy"
    try:
        client = get_redis_client()
        if client is None:
            redis_health = "unhealthy"
    except Exception:
        redis_health = "unhealthy"
        
    orch_host = vc_get("urls.orchestrator_host", "127.0.0.1")
    media_host = vc_get("urls.media_gateway_host", "127.0.0.1")
    orch_port = vc_get("ports.orchestrator", 8000)
    media_port = vc_get("ports.media_gateway", 8001)
    timeout = vc_get("health.check_timeout_s", 0.5)
    
    orch_health = "healthy"
    try:
        r = requests.get(f"http://{orch_host}:{orch_port}/health", timeout=timeout)
        if r.status_code != 200:
            orch_health = "unhealthy"
    except Exception:
        orch_health = "unhealthy"
        
    media_health = "healthy"
    try:
        r = requests.get(f"http://{media_host}:{media_port}/health", timeout=timeout)
        if r.status_code != 200:
            media_health = "unhealthy"
    except Exception:
        media_health = "unhealthy"
        
    return {
        "redis": redis_health,
        "orchestrator": orch_health,
        "media_gateway": media_health,
        "api_gateway": "healthy"
    }

# Global token metrics tracker
_token_metrics = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "cost": 0.0
}

class CancelRequest(BaseModel):
    session_id: str
    reason: str = "stop_button"

class ResetRequest(BaseModel):
    session_id: str

@app.post("/control/cancel")
async def control_cancel(req: CancelRequest):
    """Sends a kill signal to stop TTS playback and resets FSM state to listening or interrupted."""
    from services.orchestrator.cancellation_manager import cancellation_manager
    from services.orchestrator.fsm import get_fsm_for_session
    from services.orchestrator.async_pipeline import get_cancel_token, get_pipeline
    
    cancel_token = get_cancel_token(req.session_id)
    cancel_token.cancel(req.reason)
    cancellation_manager.cancel_session(req.session_id, req.reason)
    
    pipeline = get_pipeline()
    await pipeline.submit_cancel(req.session_id, req.reason)
    
    from services.orchestrator.tts_client import kill as tts_kill
    try:
        tts_kill(req.session_id)
    except Exception:
        pass
        
    fsm = get_fsm_for_session(req.session_id)
    if req.reason == "vad_interrupted":
        fsm.transition("interrupted")
    else:
        fsm.transition("listening")
    telemetry_bus.push("cancellation", {"reason": req.reason, "fsm_state": fsm.state}, req.session_id, str(fsm.turn_id))
    return {"status": "ok", "msg": f"Response canceled due to {req.reason}."}

@app.post("/control/reset")
async def control_reset(req: ResetRequest):
    """Clears conversational history from Redis and resets FSM turn counters."""
    from services.orchestrator.state_store import clear_session
    from services.orchestrator.fsm import get_fsm_for_session
    try:
        clear_session(req.session_id)
    except Exception:
        pass
    fsm = get_fsm_for_session(req.session_id)
    fsm.state = "idle"
    fsm.turn_id = 0
    fsm.last_llm_latency = 0
    fsm.last_tts_latency = 0
    fsm.last_total_latency = 0
    reset_token_budget(req.session_id)
    return {"status": "ok", "msg": "Session memory flushed, FSM reset, token budget cleared."}

class LimitsRequest(BaseModel):
    normal_max_tokens: int
    normal_max_sentences: int
    detail_max_tokens: int
    detail_max_sentences: int
    speech_rate: float = 1.0
    stt_language: str = "en-US"
    tts_voice: str = "sonic-english"

@app.get("/control/limits")
async def get_runtime_limits():
    from common.config.runtime_limits import get_limits
    return get_limits()

@app.post("/control/limits")
async def update_runtime_limits(req: LimitsRequest):
    from common.config.runtime_limits import set_limits
    set_limits(
        req.normal_max_tokens,
        req.normal_max_sentences,
        req.detail_max_tokens,
        req.detail_max_sentences,
        req.speech_rate,
        req.stt_language,
        req.tts_voice
    )
    return {"status": "ok", "msg": "Limits updated successfully."}

@app.post("/control/shutdown")
async def control_shutdown():
    """Gracefully terminates the API Gateway process."""
    from services.orchestrator.async_pipeline import shutdown_pipeline
    await shutdown_pipeline()
    import os
    import signal
    os.kill(os.getpid(), signal.SIGINT)
    return {"status": "ok", "msg": "Server shutting down..."}

def get_resource_usage():
    import threading
    import asyncio
    
    threads = threading.active_count()
    try:
        async_tasks = len(asyncio.all_tasks())
    except Exception:
        async_tasks = 1
        
    ram_base = vc_get("resource_usage.ram_base", 32.0)
    ram_per_thread = vc_get("resource_usage.ram_per_thread", 0.5)
    ram_per_task = vc_get("resource_usage.ram_per_task", 0.1)
    cpu_base = vc_get("resource_usage.cpu_base", 90.0)
    cpu_per_task = vc_get("resource_usage.cpu_per_task", 1.5)
    cpu_per_thread = vc_get("resource_usage.cpu_per_thread", 0.2)
    
    ram = round(ram_base + (threads * ram_per_thread) + (async_tasks * ram_per_task), 1)
    cpu = round(min(cpu_base, (async_tasks * cpu_per_task) + (threads * cpu_per_thread)), 1)
        
    return {"cpu": cpu, "ram": ram, "threads": threads, "async_tasks": async_tasks}

def check_url(url):
    import requests
    try:
        r = requests.get(url, timeout=vc_get("health.async_check_timeout_s", 0.3))
        return "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        return "unhealthy"

async def get_services_health_async():
    import asyncio
    from services.orchestrator.state_store import get_redis_client
    
    orch_host = vc_get("urls.orchestrator_host", "127.0.0.1")
    media_host = vc_get("urls.media_gateway_host", "127.0.0.1")
    orch_port = vc_get("ports.orchestrator", 8000)
    media_port = vc_get("ports.media_gateway", 8001)
    
    def check_redis():
        try:
            client = get_redis_client()
            return "healthy" if client is not None else "unhealthy"
        except Exception:
            return "unhealthy"
            
    redis_task = asyncio.to_thread(check_redis)
    orch_task = asyncio.to_thread(check_url, f"http://{orch_host}:{orch_port}/health")
    media_task = asyncio.to_thread(check_url, f"http://{media_host}:{media_port}/health")
    
    redis_res, orch_res, media_res = await asyncio.gather(redis_task, orch_task, media_task)
    
    return {
        "redis": redis_res,
        "orchestrator": orch_res,
        "media_gateway": media_res,
        "api_gateway": "healthy"
    }

@app.get("/telemetry")
async def get_telemetry():
    resources = get_resource_usage()
    services = await get_services_health_async()
    
    def get_stats(key):
        vals = _metrics_history[key]
        if not vals:
            return {"curr": 0, "avg": 0, "min": 0, "max": 0, "p95": 0, "p99": 0}
        return {
            "curr": vals[-1],
            "avg": int(sum(vals) / len(vals)),
            "min": min(vals),
            "max": max(vals),
            "p95": calculate_percentile(vals, 95),
            "p99": calculate_percentile(vals, 99)
        }
        
    return {
        "resources": resources,
        "services": services,
        "tokens": _token_metrics,
        "llm": get_stats("llm"),
        "tts": get_stats("tts"),
        "total": get_stats("total")
    }

def stream_sentences(session_id, history, turn_id):
    import time
    from common.config.settings import get_settings
    from services.orchestrator.cancellation_manager import cancellation_manager
    
    settings = get_settings()
    api_key = settings.groq_api_key
    
    if not api_key or api_key == "dummy_val" or settings.env == "test":
        sentences = vc_get("mock.mock_stream_sentences", [
            "Hello there!",
            "I am your streaming voice assistant.",
            "How can I help you today?"
        ])
        for s in sentences:
            if cancellation_manager.is_cancelled(session_id):
                break
            time.sleep(vc_get("sentence_streaming_delay_s", 0.08))
            yield s
        return

    from groq import Groq
    client = Groq(api_key=api_key)

    context_history = prepare_context(history, session_id)
    system_prompt = vc_get("llm.system_prompt", "You are a helpful, concise voice assistant.")
    payload = [
        {"role": "system", "content": system_prompt}
    ] + context_history

    budget = get_token_budget(session_id)
    from services.orchestrator.context_manager import estimate_tokens
    prompt_tok = estimate_tokens(system_prompt) + sum(estimate_tokens(m.get("content", "")) for m in context_history)
    budget.record_prompt(prompt_tok)
    
    chat_completion = client.chat.completions.create(
        messages=payload,
        model=settings.groq_model,
        stream=True
    )
    
    buffer = []
    sentence_endings = {'.', '?', '!', '\n'}
    first_token_emitted = False
    token_count = 0
    stream_start = time.time()
    
    for chunk in chat_completion:
        if cancellation_manager.is_cancelled(session_id):
            telemetry_bus.push("cancellation", {"reason": "stream_aborted", "tokens_yielded": token_count}, session_id, turn_id)
            break
        delta = chunk.choices[0].delta.content or ""
        if not delta:
            continue
        if not first_token_emitted:
            first_token_emitted = True
            ttfb = int((time.time() - stream_start) * 1000)
            telemetry_bus.push("llm_first_token", {"latency_ms": ttfb}, session_id, turn_id)
        token_count += 1
        buffer.append(delta)
        # If we hit punctuation, check if we completed a sentence
        if any(char in sentence_endings for char in delta):
            text_so_far = "".join(buffer).strip()
            if text_so_far:
                yield text_so_far
                buffer.clear()
                
    if buffer:
        remaining = "".join(buffer).strip()
        if remaining:
            yield remaining
    
    elapsed = max(0.001, time.time() - stream_start)
    tokens_per_sec = round(token_count / elapsed, 1)
    budget = get_token_budget(session_id)
    budget.record_completion(token_count)
    telemetry_bus.push("llm_tokens", {"token_count": token_count, "tokens_per_sec": tokens_per_sec,
                                      "cumulative_prompt": budget.prompt_tokens,
                                      "cumulative_completion": budget.completion_tokens,
                                      "budget_pct": budget.usage_pct}, session_id, turn_id)

async def run_llm_tts_pipeline(session_id: str, text: str, audio_queue: asyncio.Queue):
    import time
    import asyncio
    from services.orchestrator.fsm import get_fsm_for_session
    from services.orchestrator.state_store import load_history, save_turn
    from services.orchestrator.cancellation_manager import cancellation_manager
    from services.orchestrator.tts_client import speak_stream
    
    fsm = get_fsm_for_session(session_id)
    fsm.turn_id += 1
    turn_id_str = str(fsm.turn_id)
    fsm.transition("thinking")
    telemetry_bus.push("llm_request", {"text": text[:80]}, session_id, turn_id_str)
    
    history = load_history(session_id)
    history.append({"role": "user", "content": text})
    save_turn(session_id, turn_id_str, "user", text)
    
    telemetry_bus.push("vad_final", {"text": text[:80]}, session_id, turn_id_str)
    
    fsm.transition("speaking")
    full_response_text = []
    first_token_emitted = False
    
    def process_sentences():
        nonlocal first_token_emitted
        try:
            for idx, sentence in enumerate(stream_sentences(session_id, history, turn_id_str)):
                if cancellation_manager.is_cancelled(session_id):
                    break
                if not first_token_emitted:
                    first_token_emitted = True
                    telemetry_bus.push("tts_start", {"sentence_idx": idx}, session_id, turn_id_str)
                full_response_text.append(sentence)
                
                def chunk_callback(chunk):
                    if not cancellation_manager.is_cancelled(session_id):
                        audio_queue.put_nowait(chunk)
                        
                speak_stream(session_id, turn_id_str, sentence, chunk_callback)
                telemetry_bus.push("tts_chunk", {"sentence": sentence[:40]}, session_id, turn_id_str)
        except Exception as e:
            print("Error in process_sentences:", e)
            
    # Run synchronously in a thread pool to avoid blocking the event loop
    await asyncio.to_thread(process_sentences)
    
    reply_text = " ".join(full_response_text)
    if reply_text and not cancellation_manager.is_cancelled(session_id):
        save_turn(session_id, str(fsm.turn_id), "assistant", reply_text)
        
    fsm.transition("listening")

@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    logger.log("ws_connected", "system", "system", detail={})
    
    from common.config import voice_settings
    q_size = voice_settings.get("concurrency.websocket_queue_size", 100)
    write_timeout = voice_settings.get("concurrency.websocket_write_timeout_s", 5.0)
    
    session_id = None
    audio_queue = asyncio.Queue(maxsize=q_size)
    active_tasks = []
    pipeline = None
    
    try:
        pipeline = get_pipeline()
        pipeline.start()
        logger.log("pipeline_started", "system", "system", detail={})
    except Exception as e:
        logger.log_error("pipeline_start_error", "system", "system", e)
        await websocket.send_json({"type": "error", "detail": "Pipeline initialization failed"})
        await websocket.close()
        return
    
    async def send_audio_loop():
        try:
            while True:
                chunk = await audio_queue.get()
                if isinstance(chunk, dict):
                    await asyncio.wait_for(websocket.send_json(chunk), timeout=write_timeout)
                else:
                    await asyncio.wait_for(websocket.send_bytes(chunk), timeout=write_timeout)
                audio_queue.task_done()
        except asyncio.CancelledError:
            logger.log("ws_send_loop_cancelled", session_id or "?", "system", detail={})
        except asyncio.TimeoutError:
            logger.log_error("ws_send_timeout", session_id or "?", "system", Exception("WebSocket send timed out"))
            try:
                await websocket.close()
            except Exception:
                pass
        except Exception as e:
            logger.log_error("ws_send_error", session_id or "?", "system", e)
    
    send_task = asyncio.create_task(send_audio_loop())

    active_tasks.append(send_task)
    
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception as e:
                logger.log_error("ws_receive_error", session_id or "?", "system", e)
                continue
                
            if data.get("type") == "transcript":
                session_id = data["session_id"]
                text = data["text"]
                
                logger.log("stt_received", session_id, "system",
                           detail={"text": text[:80]})
                
                try:
                    cancel_token = get_cancel_token(session_id)
                    cancel_token.reset()
                    
                    pipeline.register_playback_client(session_id, audio_queue)
                    
                    await pipeline.submit_transcript(session_id, text)
                    logger.log("transcript_submitted", session_id, "system", detail={"text_len": len(text)})
                except Exception as e:
                    logger.log_error("transcript_submit_failed", session_id, "system", e)
                    await websocket.send_json({"type": "error", "detail": f"Failed to process transcript: {str(e)}"})
                    
            elif data.get("type") == "cancel":
                if session_id:
                    try:
                        await pipeline.submit_cancel(session_id, "user_cancel")
                        await pipeline.submit_interrupt(session_id, "stop_button")
                        while not audio_queue.empty():
                            try:
                                audio_queue.get_nowait()
                                audio_queue.task_done()
                            except asyncio.QueueEmpty:
                                break
                        # Include current turn_id so the client's tag-validation
                        # guard (currentServerTurnId) can reject any in-flight
                        # stale binary frames arriving after this cancel.
                        current_turn = pipeline.fsm.get_session_turn_id(session_id)
                        await websocket.send_json({"type": "stop_audio", "turn_id": current_turn})
                        logger.log("cancel_handled", session_id, "system", detail={"reason": "user_cancel"})

                    except Exception as e:
                        logger.log_error("cancel_failed", session_id, "system", e)
                        
    except WebSocketDisconnect:
        logger.log("ws_disconnected", session_id or "?", "system", detail={})
    except Exception as e:
        logger.log_error("ws_error", session_id or "?", "system", e)
    finally:
        if session_id:
            try:
                from services.orchestrator.cancellation_manager import cancellation_manager
                # Trigger cancellation to immediately stop LLM and TTS tasks in flight
                cancellation_manager.cancel_session(session_id, "websocket_disconnect")
                token = get_cancel_token(session_id)
                token.cancel("websocket_disconnect")
                if pipeline:
                    pipeline.unregister_playback_client(session_id)
            except Exception as e:
                logger.log_error("ws_cleanup_failed", session_id, "system", e)
        for task in active_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.log_error("task_cancel_failed", session_id or "?", "system", e)
        # Drain any residual audio chunks left in the gateway queue after
        # send_audio_loop has exited, to release memory immediately.
        while not audio_queue.empty():
            try:
                audio_queue.get_nowait()
                audio_queue.task_done()
            except asyncio.QueueEmpty:
                break

        # Shut down the entire pipeline and server process on leave/disconnect to save all resources and tokens
        try:
            logger.log("ws_shutdown_trigger", session_id or "system", "system", detail={"msg": "Shutting down pipeline and releasing resources due to disconnect."})
            
            # Clear all in-memory semantic cache entries to save memory and avoid residual caches
            try:
                from services.orchestrator.cache_client import cache_manager
                cache_manager.store.store.clear()
                logger.log("cache_cleared", session_id or "system", "system", detail={"msg": "Semantic cache cleared successfully."})
            except Exception as e:
                logger.log_error("cache_clear_failed", session_id or "system", "system", e)

            from services.orchestrator.async_pipeline import shutdown_pipeline
            await shutdown_pipeline()
        except Exception as e:
            logger.log_error("ws_shutdown_failed", session_id or "system", "system", e)

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue()
    history = telemetry_bus.register(queue)
    
    snapshot_size = vc_get("telemetry.ws_history_snapshot", 100)
    for event in history[-snapshot_size:]:
        try:
            await websocket.send_json(event)
        except Exception:
            break
    
    try:
        while True:
            payload = await queue.get()
            try:
                await websocket.send_text(payload)
            except Exception:
                break
            queue.task_done()
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        telemetry_bus.unregister(queue)

@app.get("/config")
async def get_config():
    """Expose relevant frontend configuration."""
    return {
        "api_port": vc_get("ports.api_gateway", 8003),
        "telemetry_feed_max": vc_get("telemetry.feed_max_entries", 100),
        "browser_resource_interval_ms": vc_get("ui.browser_resource_interval_ms", 5000),
        "telemetry_refresh_rate_ms": vc_get("telemetry.dashboard_refresh_rate_ms", 2000),
        "ws_reconnect_delay_ms": vc_get("telemetry.ws_reconnect_delay_ms", 3000),
        "latency_thresholds": vc_get("latency_thresholds", {}),
        "state_timeouts": vc_get("state_timeouts", {}),
        "ui": vc_get("ui", {}),
        "stt_language": vc_get("stt.language", "en-US"),
        "stt_interim_results": vc_get("stt.interim_results", False),
        "volume_percent_cap": vc_get("volume.percent_cap", 100),
        "volume_rms_multiplier": vc_get("volume.rms_multiplier", 400),
        "fallback_stt_latency": vc_get("fallback_stt_latency", 180),
        "latency_threshold_targets": {
            "stt": vc_get("latency_thresholds.stt", 250),
            "llm": vc_get("latency_thresholds.llm", 800),
            "tts": vc_get("latency_thresholds.tts", 250),
            "network": vc_get("latency_thresholds.network", 150),
            "interruption": vc_get("latency_thresholds.interruption", 100),
            "total": vc_get("latency_thresholds.total", 1200)
        },
        "context": {
            "sliding_window": {
                "max_turns": vc_get("context.sliding_window.max_turns", 10),
                "enabled": vc_get("context.sliding_window.enabled", True)
            },
            "summarization": {
                "enabled": vc_get("context.summarization.enabled", True)
            },
            "deduplication": {
                "enabled": vc_get("context.deduplication.enabled", True)
            },
            "compression": {
                "enabled": vc_get("context.compression.enabled", True)
            },
            "token_budget": {
                "per_turn": vc_get("context.token_budget.per_turn", 2048),
                "per_session": vc_get("context.token_budget.per_session", 16384),
                "warn_at": vc_get("context.token_budget.warn_at", 0.8)
            }
        }
    }

@app.get("/token-budget/{session_id}")
async def token_budget_route(session_id: str):
    budget = get_token_budget(session_id)
    return budget.to_dict()

@app.get("/token-budget/{session_id}/reset")
async def token_budget_reset(session_id: str):
    reset_token_budget(session_id)
    return {"status": "ok", "msg": "Token budget reset for session."}

@app.get("/health")
async def health():
    from services.orchestrator.state_store import get_redis_client
    
    redis_info = {"status": "unknown"}
    client = get_redis_client()
    
    if client is None:
        redis_info = {"status": "unconfigured", "msg": "Redis not configured or disabled"}
    else:
        try:
            # Test connection with detailed info
            ping_result = client.ping()
            info = client.info("memory")
            redis_info = {
                "status": "healthy" if ping_result else "unhealthy",
                "ping": ping_result,
                "memory_used_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
                "connected_clients": info.get("connected_clients", 0),
            }
        except Exception as e:
            redis_info = {
                "status": "unhealthy",
                "error": str(e),
                "error_type": type(e).__name__,
            }
    
    return {
        "status": "healthy" if redis_info.get("status") == "healthy" else "degraded",
        "redis": redis_info,
    }

_telemetry_task = None

async def telemetry_background_loop():
    while True:
        try:
            await asyncio.sleep(2.0)
            # Calculate resources
            resources = await asyncio.to_thread(get_resource_usage)
            telemetry_bus.push("resource_usage", resources, "system", "system")
            
            # Check services health
            services = await get_services_health_async()
            # Push Redis status specifically
            telemetry_bus.push("redis_status", {"status": services["redis"]}, "system", "system")
            # Push other services status
            telemetry_bus.push("services_status", services, "system", "system")
            
            # Push worker status
            pipeline = get_pipeline()
            worker_states = {}
            if pipeline:
                for stage in [pipeline.stt, pipeline.llm, pipeline.tts, pipeline.playback,
                              pipeline.fsm, pipeline.interrupt, pipeline.metrics]:
                    task_active = pipeline._started and stage._task is not None and not stage._task.done()
                    worker_states[stage.name] = "active" if task_active else "inactive"
                    # Track queue length for queue_update
                    if hasattr(stage, "input") and isinstance(stage.input, asyncio.Queue):
                        q_len = stage.input.qsize()
                        if q_len > 0:
                            telemetry_bus.push("queue_update", {"length": q_len, "stage": stage.name}, "system", "system")
            telemetry_bus.push("worker_status", worker_states, "system", "system")
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.log_error("telemetry_background_loop_error", "system", "system", e)

@app.on_event("startup")
async def startup_event():
    global _telemetry_task
    _telemetry_task = asyncio.create_task(telemetry_background_loop())
    logger.log("api_gateway_started", "system", "system", detail={})

if __name__ == "__main__":
    import uvicorn
    port = vc_get("ports.api_gateway", 8003)
    uvicorn.run(app, host="0.0.0.0", port=port)

# Application lifecycle events
@app.on_event("shutdown")
async def shutdown_event():
    global _telemetry_task
    if _telemetry_task:
        _telemetry_task.cancel()
        try:
            await _telemetry_task
        except asyncio.CancelledError:
            pass
    logger.log_service_stop("api-gateway", detail={"reason": "application_shutdown"})
    from services.orchestrator.async_pipeline import shutdown_pipeline
    await shutdown_pipeline()
