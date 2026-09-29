from datetime import datetime, timezone

from sqlalchemy.orm import Session

from emotion.classifier import EmotionResult
from emotion.strategy import ResponseStrategy
from models import EmotionalMemory

RECENT_EMOTIONS_KEPT = 10


def get_recent_emotions(db: Session, user_id: str) -> list[dict]:
    row = db.get(EmotionalMemory, user_id)
    return list(row.recent_emotions) if row else []


def record_emotion(db: Session, user_id: str, result: EmotionResult) -> None:
    """Adds to the caller's transaction; the caller commits."""
    row = db.get(EmotionalMemory, user_id)
    entry = {
        "emotion": result.emotion,
        "confidence": round(result.confidence, 2),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if row is None:
        db.add(EmotionalMemory(user_id=user_id, recent_emotions=[entry]))
    else:
        row.recent_emotions = [*row.recent_emotions, entry][-RECENT_EMOTIONS_KEPT:]
        row.updated_at = datetime.now(timezone.utc)


EMPATHY_PRINCIPLES = """You are emotionally intelligent. Read the user's emotional state and respond like a caring, perceptive person would:
- Listen patiently; never rush past what they said.
- Acknowledge their feelings before offering advice or solutions.
- Use encouraging, respectful, non-judgmental language.
- Ask a thoughtful follow-up question when it fits naturally.
- Never pretend to be human, and never diagnose or replace professional mental health help — gently suggest it if things sound serious."""


def build_emotion_context(result: EmotionResult, strategy: ResponseStrategy, recent_emotions: list[dict]) -> str:
    lines = [
        EMPATHY_PRINCIPLES,
        "",
        f"The user's latest message reads as: {result.emotion} (confidence {result.confidence:.2f}).",
        f"Response strategy: {strategy.name}. {strategy.guidance}",
        f"Your tone should be {strategy.tone}. Do not simply mirror the user's emotion.",
    ]
    if recent_emotions:
        recent_list = ", ".join(e["emotion"] for e in recent_emotions)
        lines.append(
            f"Recently this user has tended to feel: {recent_list}. "
            "Use this only as soft context, not a label to repeat back to them."
        )
    return "\n".join(lines)
