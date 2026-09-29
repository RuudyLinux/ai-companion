from voice.engine_base import VoiceEngine
from voice import xtts


class XTTSEngine(VoiceEngine):
    name = "development"

    def synthesize(self, text, out_path, language="en", speaker_wav=None, speaker_name=None):
        xtts.synthesize(text, out_path, language=language, speaker_wav=speaker_wav, speaker_name=speaker_name)

    def builtin_speakers(self):
        return xtts.builtin_speaker_names()

    def supports_language(self, xtts_style_code):
        return xtts_style_code in xtts.SUPPORTED_LANGUAGES
