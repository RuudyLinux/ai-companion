"""Local speech-to-text via faster-whisper — fully offline, no API calls."""

from functools import lru_cache

from faster_whisper import WhisperModel


@lru_cache(maxsize=1)
def _model() -> WhisperModel:
    # "base" balances speed/accuracy for CPU-only inference; int8 keeps it fast without a GPU.
    return WhisperModel("base", device="cpu", compute_type="int8")


def transcribe(audio_path: str) -> str:
    segments, _info = _model().transcribe(audio_path, beam_size=5)
    return " ".join(segment.text.strip() for segment in segments).strip()
