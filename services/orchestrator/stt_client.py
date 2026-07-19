from common.config.settings import get_settings
from common.logging.logger import get_logger
from services.orchestrator.fsm import get_fsm_for_session
from deepgram import DeepgramClient

logger = get_logger("stt-client")

def handle_transcript(session_id: str, transcript: str, is_final: bool, latency_ms: int = 0):
    """Callback triggered on STT transcripts from Deepgram."""
    # Phase 1 uses turn_id 1 by default
    turn_id = "1"
    
    if is_final:
        logger.log(
            event_name="stt_final",
            session_id=session_id,
            turn_id=turn_id,
            latency_ms=latency_ms,
            detail={"text": transcript}
        )
        fsm = get_fsm_for_session(session_id)
        fsm.receive_transcript(transcript)
    else:
        logger.log(
            event_name="stt_partial",
            session_id=session_id,
            turn_id=turn_id,
            latency_ms=latency_ms,
            detail={"text": transcript}
        )

def transcribe_audio_file(session_id: str, filepath: str) -> str:
    """Helper method to transcribe pre-recorded audio files for testing and validation."""
    settings = get_settings()
    api_key = settings.deepgram_api_key
    
    from common.config.voice_settings import get as vc_get
    if not api_key or api_key == "dummy_val" or settings.env == "test":
        transcript = vc_get("mock.stt_transcript", "What's the weather like on Mars?")
        handle_transcript(session_id, transcript, is_final=True)
        return transcript
        
    # Real Deepgram API call

    deepgram = DeepgramClient(api_key)
    
    with open(filepath, "rb") as file:
        buffer_data = file.read()
        response = deepgram.listen.v1.media.transcribe_file(
            buffer_data,
            model=vc_get("stt.model_id", "nova-3"),
            smart_format=True
        )
        transcript = response.results.channels[0].alternatives[0].transcript
        handle_transcript(session_id, transcript, is_final=True)
        return transcript
