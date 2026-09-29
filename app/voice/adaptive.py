"""
Dynamic Voice Adaptation Engine — picks a DSP preset (from voice/effects.py's
EMOTION_EFFECTS/VOICE_CHANGER_STYLES) automatically instead of requiring the user to pick
one manually every message, then scales it by that user's own speed/volume/intensity
preferences. Voice identity itself is never touched — this only reshapes the delivery of
whatever voice already spoke, same as the existing manual effect-preset feature.

Primary signal is the assistant's OWN finished reply text (classified with the existing
emotion/classifier.py), not the user's message — a caring reply to an angry user should
sound calm, not angry, so the reply's own tone is a stronger signal than mirroring the
user. The user's emotion is only consulted as a fallback when the reply reads neutral.

Deliberately out of scope, not silently faked:
  - Pause duration / pronunciation emphasis: no TTS backend in use (XTTS, F5-TTS, Inworld)
    supports SSML/timing markup.
  - Independent pitch control: the underlying _speed() DSP op couples speed+pitch
    (tape-speed shift) by deliberate, tested design (see effects.py) — there is no
    separate pitch knob anywhere in this engine.
  - Per-user timezone-aware time-of-day: User has no timezone field, so this uses server
    local time and only nudges a "night" bucket — not full 4-bucket differentiation.
"""

from datetime import datetime

from emotion.classifier import classify_emotion
from voice.effects import EMOTION_EFFECTS, VOICE_CHANGER_STYLES

NEUTRAL_PRESET = "friendly"

EMOTION_TO_PRESET = {
    "happy": "happy", "sad": "sad", "angry": "angry",
    "frustrated": "serious", "stressed": "calm", "anxious": "calm",
    "excited": "excited", "nervous": "calm", "lonely": "emotional",
    "confused": "serious", "fearful": "fear", "calm": "calm",
    "curious": "friendly", "surprised": "surprised", "neutral": "friendly",
}

CONVERSATION_TYPE_KEYWORDS = {
    "professional": ("professional", "business", "work", "career", "formal", "corporate", "consultant"),
    "educational": ("teacher", "tutor", "explain", "learn", "study", "educat"),
    "motivational": ("motivat", "coach", "inspire", "encourage", "cheer"),
}  # anything else -> "casual"

CONVERSATION_TYPE_PRESET_BIAS = {
    "professional": "serious",
    "educational": "serious",
    "motivational": "motivational",
    "casual": "friendly",
}

TIME_OF_DAY_PRESET_BIAS = {"night": "calm"}  # 22:00-05:00 only, a light nudge — see module docstring

_TIMBRAL_OPS_INTENSITY_THRESHOLD = 0.35  # bandpass/ring_mod/echo have no continuous identity value to blend toward


def _infer_conversation_type(persona_prompt: str) -> str:
    text = (persona_prompt or "").lower()
    for style, keywords in CONVERSATION_TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return style
    return "casual"


def _time_of_day_bucket(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    if hour >= 22 or hour < 5:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def resolve_adaptive_effect(
    assistant_reply_text: str,
    user_message_text: str | None,
    persona_prompt: str,
    formal_casual: str,
    now: datetime | None = None,
) -> str:
    """Picks an EMOTION_EFFECTS/VOICE_CHANGER_STYLES preset key for this reply. Always
    returns a valid preset key (falls all the way back to NEUTRAL_PRESET)."""
    preset = EMOTION_TO_PRESET.get(classify_emotion(assistant_reply_text), NEUTRAL_PRESET)

    if preset == NEUTRAL_PRESET and user_message_text:
        user_preset = EMOTION_TO_PRESET.get(classify_emotion(user_message_text), NEUTRAL_PRESET)
        if user_preset != NEUTRAL_PRESET:
            preset = user_preset

    if preset == NEUTRAL_PRESET:
        conversation_type = _infer_conversation_type(persona_prompt)
        preset = CONVERSATION_TYPE_PRESET_BIAS.get(conversation_type, NEUTRAL_PRESET)

    if preset == NEUTRAL_PRESET:
        bucket = _time_of_day_bucket(now)
        preset = TIME_OF_DAY_PRESET_BIAS.get(bucket, NEUTRAL_PRESET)

    # Last resort only: if nothing above resolved anything (reply emotion, user emotion,
    # conversation type, and time of day were all inconclusive), fall back to the user's
    # formal/casual style preference instead of always defaulting to "friendly". This must
    # never fire once *any* earlier stage has produced a real, non-neutral preset — e.g. a
    # reply that reads as "confused" should stay mapped to "serious" regardless of the
    # user's style preference, not get overwritten back down to "friendly".
    if preset == NEUTRAL_PRESET and formal_casual in ("formal", "casual"):
        preset = "serious" if formal_casual == "formal" else "friendly"

    return preset


def resolve_scaled_chain(
    effect_name: str | None,
    intensity: float = 1.0,
    speed_bias: float = 1.0,
    volume_bias_db: float = 0.0,
) -> list[tuple[str, dict]]:
    """Builds the actual DSP chain to apply: the chosen preset's steps scaled by how
    strongly moods should affect delivery (intensity), plus the user's own speed/volume
    baseline preferences layered on top — the baseline always applies, even with no
    preset selected (explicit Neutral), since it's a general delivery preference."""
    base_chain: list[tuple[str, dict]] = []
    if effect_name:
        base_chain = EMOTION_EFFECTS.get(effect_name) or VOICE_CHANGER_STYLES.get(effect_name) or []

    scaled: list[tuple[str, dict]] = []
    has_speed = has_gain = False

    for fn_name, kwargs in base_chain:
        if fn_name == "speed":
            scaled.append(("speed", {"rate": 1.0 + (kwargs["rate"] - 1.0) * intensity}))
            has_speed = True
        elif fn_name == "gain":
            scaled.append(("gain", {"db": kwargs["db"] * intensity}))
            has_gain = True
        elif intensity >= _TIMBRAL_OPS_INTENSITY_THRESHOLD:
            scaled.append((fn_name, kwargs))

    if speed_bias != 1.0:
        if has_speed:
            scaled = [
                ("speed", {"rate": kw["rate"] * speed_bias}) if fn == "speed" else (fn, kw) for fn, kw in scaled
            ]
        else:
            scaled.append(("speed", {"rate": speed_bias}))

    if volume_bias_db != 0.0:
        if has_gain:
            scaled = [
                ("gain", {"db": kw["db"] + volume_bias_db}) if fn == "gain" else (fn, kw) for fn, kw in scaled
            ]
        else:
            scaled.append(("gain", {"db": volume_bias_db}))

    return scaled
