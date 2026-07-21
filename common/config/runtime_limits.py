import os
from common.config.voice_settings import get as vc_get

_normal_max_tokens = None
_normal_max_sentences = None
_detail_max_tokens = None
_detail_max_sentences = None
_speech_rate = 1.0
_stt_language = "en-US"
_tts_voice = "sonic-english"

def get_limits():
    global _normal_max_tokens, _normal_max_sentences, _detail_max_tokens, _detail_max_sentences, _speech_rate, _stt_language, _tts_voice
    if _normal_max_tokens is None:
        _normal_max_tokens = vc_get("llm.max_tokens", 256)
    if _normal_max_sentences is None:
        _normal_max_sentences = vc_get("llm.max_sentences", 3)
    if _detail_max_tokens is None:
        _detail_max_tokens = 600
    if _detail_max_sentences is None:
        _detail_max_sentences = 10

    return {
        "normal_max_tokens": _normal_max_tokens,
        "normal_max_sentences": _normal_max_sentences,
        "detail_max_tokens": _detail_max_tokens,
        "detail_max_sentences": _detail_max_sentences,
        "speech_rate": _speech_rate,
        "stt_language": _stt_language,
        "tts_voice": _tts_voice,
    }

def set_limits(normal_tokens, normal_sentences, detail_tokens, detail_sentences, speech_rate=1.0, stt_language="en-US", tts_voice="sonic-english"):
    global _normal_max_tokens, _normal_max_sentences, _detail_max_tokens, _detail_max_sentences, _speech_rate, _stt_language, _tts_voice
    _normal_max_tokens = int(normal_tokens)
    _normal_max_sentences = int(normal_sentences)
    _detail_max_tokens = int(detail_tokens)
    _detail_max_sentences = int(detail_sentences)
    _speech_rate = float(speech_rate)
    _stt_language = str(stt_language)
    _tts_voice = str(tts_voice)
