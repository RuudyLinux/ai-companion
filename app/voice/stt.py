"""Local speech-to-text via faster-whisper — fully offline, no API calls.
Only imported inside the transcription child process (see voice/stt_runner.py)."""

from functools import lru_cache

from faster_whisper import WhisperModel

from core.config import settings


@lru_cache(maxsize=1)
def _model() -> WhisperModel:
    # defaults ("base", cpu, int8) balance speed/accuracy without needing a GPU
    return WhisperModel(settings.stt_model, device=settings.stt_device, compute_type=settings.stt_compute_type)


def transcribe(audio_path: str) -> tuple[str, str | None]:
    segments, info = _model().transcribe(audio_path, beam_size=5)
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text, getattr(info, "language", None)
