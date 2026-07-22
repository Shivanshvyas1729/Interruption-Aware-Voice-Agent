from common.config.voice_settings import get as vc_get, get_voice_config

def load_interruption_config() -> dict:
    c = get_voice_config()
    return {
        "confidence_thresholds": c.get("interruption", {}).get("confidence_thresholds", {}),
        "timing": {
            "min_speech_duration_ms": vc_get("interruption.min_speech_duration_ms", 200),
            "max_backchannel_duration_ms": vc_get("interruption.max_backchannel_duration_ms", 800),
            "cancellation_timeout_ms": vc_get("interruption.interrupt_timeout_ms", 100),
            "vad_sensitivity": vc_get("interruption.vad_threshold", 0.5),
        },
        "categories": c.get("categories", {}),
        "weights": c.get("interruption", {}).get("weights", {}),
    }
