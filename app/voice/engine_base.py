"""
Voice engine abstraction — one interface, three swappable backends:
  - development:       XTTS v2 (local GPU, zero-shot cloning, free, ~17 languages)
  - offline_production: F5-TTS (local GPU, different open model, also free)
  - cloud_production:  Inworld AI (cloud API, best quality, costs money, needs a key)

Callers (routers/chat.py, seed scripts) talk to whichever engine is active via
get_engine() in voice/engine.py — they never import xtts/f5tts/inworld directly.
"""

from abc import ABC, abstractmethod


class VoiceEngine(ABC):
    name: str

    # True for XTTS/F5-TTS: a "cloned" voice's speaker_ref is a raw reference wav file,
    # re-sent as speaker_wav on every synthesize() call. False for Inworld: cloning is a
    # one-time registration, and the resulting speaker_ref is a persistent voiceId used
    # exactly like a builtin preset (speaker_name) from then on.
    clone_needs_raw_file: bool = True

    @abstractmethod
    def synthesize(
        self,
        text: str,
        out_path: str,
        language: str = "en",
        speaker_wav: str | None = None,
        speaker_name: str | None = None,
    ) -> None:
        """Either speaker_wav (clone from a reference file) or speaker_name (a builtin/preset voice) must be given."""
        raise NotImplementedError

    @abstractmethod
    def builtin_speakers(self) -> list[str]:
        """Named preset voices this engine ships with (empty list if it only supports cloning)."""
        raise NotImplementedError

    @abstractmethod
    def supports_language(self, xtts_style_code: str) -> bool:
        raise NotImplementedError
