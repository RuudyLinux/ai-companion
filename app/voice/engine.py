"""
Voice engine factory — reads VOICE_ENGINE_MODE from the environment and returns the
matching engine. Callers (routers/chat.py, seed scripts) go through get_engine() and
never import a specific engine module directly, so switching modes never touches them.
"""

import os
from functools import lru_cache

from voice.engine_base import VoiceEngine

VALID_MODES = {"development", "offline_production", "cloud_production"}


@lru_cache(maxsize=1)
def get_engine() -> VoiceEngine:
    mode = os.environ.get("VOICE_ENGINE_MODE", "development").strip()
    if mode not in VALID_MODES:
        raise ValueError(f"VOICE_ENGINE_MODE must be one of {VALID_MODES}, got {mode!r}")

    if mode == "development":
        from voice.engines.xtts_engine import XTTSEngine
        return XTTSEngine()
    if mode == "offline_production":
        from voice.engines.f5tts_engine import F5TTSEngine
        return F5TTSEngine()
    from voice.engines.inworld_engine import InworldEngine
    return InworldEngine()
