"""
User emotion -> assistant response strategy -> assistant tone -> voice delivery.

The companion deliberately does NOT mirror the user: an angry user gets a calm,
de-escalating reply spoken in a controlled, slightly slower voice. Voice presets are
keys of voice/effects.py EMOTION_EFFECTS.
"""

from dataclasses import dataclass

from emotion.classifier import EmotionResult

# below this the detected emotion is too uncertain to steer the reply
MIN_CONFIDENCE_TO_ADAPT = 0.3


@dataclass(frozen=True)
class ResponseStrategy:
    name: str
    guidance: str  # instruction for the LLM
    tone: str  # how the assistant should sound, in words
    voice_preset: str  # DSP preset for TTS delivery


STRATEGIES: dict[str, ResponseStrategy] = {
    "happy": ResponseStrategy("celebrate", "Celebrate with them and share their enthusiasm.", "warm and upbeat", "happy"),
    "excited": ResponseStrategy(
        "encourage", "Match their energy and encourage their goals.", "energetic and encouraging", "excited"
    ),
    "sad": ResponseStrategy(
        "comfort",
        "Acknowledge the feeling before anything else. Respond with empathy, kindness and support; don't rush to fix.",
        "gentle and warm",
        "emotional",
    ),
    "lonely": ResponseStrategy(
        "connect",
        "Be warm and engaged, show genuine interest, and invite them to share more — without pretending to be human.",
        "warm and attentive",
        "friendly",
    ),
    "angry": ResponseStrategy(
        "de-escalate",
        "Stay calm, acknowledge their frustration without judgment, and avoid confrontation or defensiveness.",
        "calm and reassuring",
        "calm",
    ),
    "frustrated": ResponseStrategy(
        "steady-help", "Acknowledge the frustration first, then offer calm, practical help.", "patient and clear", "calm"
    ),
    "stressed": ResponseStrategy(
        "reassure",
        "Offer reassurance and one or two practical, manageable suggestions. Keep it short and grounding.",
        "calm and steady",
        "calm",
    ),
    "anxious": ResponseStrategy(
        "ground", "Be grounding and reassuring; keep responses steady and unhurried.", "soft and steady", "calm"
    ),
    "nervous": ResponseStrategy("steady", "Be gentle and reassuring; help them feel steady.", "gentle", "calm"),
    "fearful": ResponseStrategy(
        "reassure", "Be calm and steady; take the fear seriously and never dismiss it.", "calm and steady", "calm"
    ),
    "confused": ResponseStrategy(
        "clarify",
        "Give a clear, step-by-step explanation. Ask one clarifying question if needed.",
        "clear and measured",
        "serious",
    ),
    "curious": ResponseStrategy("explore", "Engage their curiosity and explore the topic with them.", "engaged", "friendly"),
    "surprised": ResponseStrategy(
        "process", "Acknowledge the surprise and help them make sense of it.", "attentive", "friendly"
    ),
    "calm": ResponseStrategy("maintain", "Keep the relaxed, easygoing tone.", "relaxed", "friendly"),
    "neutral": ResponseStrategy("inform", "Keep the conversation friendly and informative.", "friendly", "friendly"),
}


def strategy_for(result: EmotionResult | str | None) -> ResponseStrategy:
    if result is None:
        return STRATEGIES["neutral"]
    if isinstance(result, str):
        return STRATEGIES.get(result, STRATEGIES["neutral"])
    if result.confidence < MIN_CONFIDENCE_TO_ADAPT and result.source != "keyword":
        return STRATEGIES["neutral"]
    return STRATEGIES.get(result.emotion, STRATEGIES["neutral"])
