"""
Language detection + routing between "what the LLM can reply in" (any language) and
"what XTTS-v2 can actually speak aloud" (17 languages). The 8 requested Indic languages
without a local TTS voice model still get full text replies — just no generated audio.
"""

from langdetect import detect, DetectorFactory, LangDetectException

DetectorFactory.seed = 0  # deterministic detection

# name -> (langdetect code, XTTS code or None if unsupported for audio)
LANGUAGES = {
    "English": ("en", "en"),
    "Hindi": ("hi", "hi"),
    "Gujarati": ("gu", None),
    "Marathi": ("mr", None),
    "Bengali": ("bn", None),
    "Tamil": ("ta", None),
    "Telugu": ("te", None),
    "Malayalam": ("ml", None),
    "Punjabi": ("pa", None),
    "Urdu": ("ur", None),
    "Spanish": ("es", "es"),
    "French": ("fr", "fr"),
    "German": ("de", "de"),
    "Italian": ("it", "it"),
    "Portuguese": ("pt", "pt"),
    "Japanese": ("ja", "ja"),
    "Korean": ("ko", "ko"),
    "Chinese": ("zh-cn", "zh-cn"),
    "Arabic": ("ar", "ar"),
    "Russian": ("ru", "ru"),
}

_DETECT_TO_XTTS = {detect_code: xtts_code for detect_code, xtts_code in LANGUAGES.values()}
_DETECT_TO_NAME = {detect_code: name for name, (detect_code, _) in LANGUAGES.items()}


MIN_CHARS_FOR_DETECTION = 15
MIN_WORDS_FOR_DETECTION = 3


def detect_language(text: str) -> str | None:
    """
    Returns a langdetect code, or None if the text is too short/ambiguous to trust.
    langdetect is unreliable below ~15 chars / 3 words — e.g. "Hello" alone can get
    misdetected as Finnish, Somali, etc. purely from statistical noise. Callers should
    fall back to the conversation's last known language (or English) when this is None,
    rather than accepting a wild guess on a greeting or short reply.
    """
    stripped = text.strip()
    if len(stripped) < MIN_CHARS_FOR_DETECTION or len(stripped.split()) < MIN_WORDS_FOR_DETECTION:
        return None
    try:
        return detect(stripped)
    except LangDetectException:
        return None


def xtts_code_for(detect_code: str) -> str | None:
    """None means: LLM can still reply in this language, but no local TTS voice supports it."""
    return _DETECT_TO_XTTS.get(detect_code)


def display_name_for(detect_code: str) -> str:
    return _DETECT_TO_NAME.get(detect_code, detect_code)


def code_for_name(name: str) -> str | None:
    entry = LANGUAGES.get(name)
    return entry[0] if entry else None
