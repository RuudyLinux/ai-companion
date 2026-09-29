"""
F5-TTS engine (offline_production mode) — a different open-source local model from
XTTS, also GPU-accelerated. Unlike XTTS, F5-TTS needs a transcript of the reference
audio (ref_text) alongside the reference clip itself; we auto-transcribe it once via
the (subprocess-isolated) local Whisper STT and cache the result so cloning still only
needs a reference wav from the caller's point of view, same as XTTS.
"""

from functools import lru_cache
from pathlib import Path

from voice.engine_base import VoiceEngine
from voice.stt_runner import run_transcription

# F5-TTS's officially supported languages (English + Chinese trained; community
# checkpoints exist for more, but the default F5TTS_v1_Base model covers these two well).
SUPPORTED_LANGUAGES = {"en", "zh-cn"}


@lru_cache(maxsize=1)
def _model():
    from f5_tts.api import F5TTS
    return F5TTS(device="cuda")


@lru_cache(maxsize=32)
def _ref_text_for(speaker_wav: str) -> str:
    # raises on failure, and lru_cache never caches exceptions, so a transient STT
    # failure is retried next time instead of silently pinning an empty transcript
    return run_transcription(speaker_wav)["text"]


class F5TTSEngine(VoiceEngine):
    name = "f5tts"

    def synthesize(self, text, out_path, language="en", speaker_wav=None, speaker_name=None):
        if not speaker_wav:
            raise ValueError("F5-TTS only supports voice cloning from a reference file (speaker_wav)")

        ref_text = _ref_text_for(speaker_wav)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        _model().infer(ref_file=speaker_wav, ref_text=ref_text, gen_text=text, file_wave=out_path)

    def builtin_speakers(self):
        return []  # F5-TTS only clones from reference audio, no named preset voices

    def supports_language(self, xtts_style_code):
        return xtts_style_code in SUPPORTED_LANGUAGES
