"""
Coqui XTTS-v2 wrapper — GPU-accelerated, real zero-shot voice cloning + 17-language TTS.
Replaces pyttsx3 entirely (pyttsx3 has no cloning capability of any kind).
"""

import os
from functools import lru_cache
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")

CLONE_REFERENCE_WAV = r"D:/#practicals/AI companion/Helly.wav"

SUPPORTED_LANGUAGES = {"en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi"}


@lru_cache(maxsize=1)
def _model():
    from TTS.api import TTS
    return TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")


def builtin_speaker_names() -> list[str]:
    model = _model()
    return list(model.speakers) if model.speakers else []


def synthesize(
    text: str,
    out_path: str,
    language: str = "en",
    speaker_wav: str | None = None,
    speaker_name: str | None = None,
) -> None:
    """Either speaker_wav (cloned voice reference) or speaker_name (builtin XTTS speaker) must be given."""
    if language not in SUPPORTED_LANGUAGES:
        language = "en"

    model = _model()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    kwargs = {"text": text, "language": language, "file_path": out_path}
    if speaker_wav:
        kwargs["speaker_wav"] = speaker_wav
    elif speaker_name:
        kwargs["speaker"] = speaker_name
    else:
        raise ValueError("synthesize() requires speaker_wav or speaker_name")

    model.tts_to_file(**kwargs)


from voice.audio_utils import audio_duration_seconds  # noqa: E402,F401  (kept for backward-compat imports)
