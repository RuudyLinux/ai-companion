"""
Voice engine factory — returns the engine selected by VOICE_ENGINE (xtts | f5tts |
inworld; the legacy VOICE_ENGINE_MODE names development/offline_production/
cloud_production still work). Callers go through get_engine() and never import a
specific engine module directly, so switching engines never touches them.
"""

from functools import lru_cache

from core.config import settings
from voice.engine_base import VoiceEngine


@lru_cache(maxsize=1)
def get_engine() -> VoiceEngine:
    if settings.voice_engine == "xtts":
        from voice.engines.xtts_engine import XTTSEngine

        return XTTSEngine()
    if settings.voice_engine == "f5tts":
        from voice.engines.f5tts_engine import F5TTSEngine

        return F5TTSEngine()
    from voice.engines.inworld_engine import InworldEngine

    return InworldEngine()
