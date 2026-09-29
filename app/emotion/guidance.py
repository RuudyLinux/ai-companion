from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import EmotionalMemory

# Response Adaptation table from the Emotional Conversation Module spec.
EMPATHY_GUIDANCE = {
    "happy": "Celebrate, encourage, and share their enthusiasm.",
    "sad": "Respond with empathy, kindness, and emotional support. Acknowledge the feeling before anything else.",
    "angry": "Remain calm, acknowledge their frustration, and avoid confrontation.",
    "frustrated": "Acknowledge the frustration first, then offer calm, practical help.",
    "stressed": "Offer reassurance, practical suggestions, and a calming tone.",
    "anxious": "Be grounding and reassuring; keep responses steady and unhurried.",
    "excited": "Match their enthusiasm and encourage their goals.",
    "nervous": "Be gentle and reassuring; help them feel steady.",
    "lonely": "Be warm, engaging, and supportive without pretending to be human.",
    "confused": "Provide clear, step-by-step explanations. Ask a clarifying question if needed.",
    "fearful": "Be calm, steady, and reassuring; avoid dismissing the fear.",
    "calm": "Maintain the relaxed, easygoing tone.",
    "curious": "Engage their curiosity, explore the topic with them.",
    "surprised": "Acknowledge the surprise and help them process it.",
    "neutral": "Maintain a friendly and informative conversation.",
}


def get_recent_emotions(db: Session, user_id: str) -> list[dict]:
    row = db.query(EmotionalMemory).filter(EmotionalMemory.user_id == user_id).first()
    return row.recent_emotions if row else []


def record_emotion(db: Session, user_id: str, emotion: str) -> None:
    row = db.query(EmotionalMemory).filter(EmotionalMemory.user_id == user_id).first()
    entry = {"emotion": emotion, "at": datetime.now(timezone.utc).isoformat()}

    if row is None:
        row = EmotionalMemory(user_id=user_id, recent_emotions=[entry])
        db.add(row)
    else:
        updated = [*row.recent_emotions, entry][-10:]
        row.recent_emotions = updated
        row.updated_at = datetime.now(timezone.utc)

    db.commit()


def build_empathy_system_prompt(persona_prompt: str, current_emotion: str, recent_emotions: list[dict]) -> str:
    recent_pattern = ""
    if recent_emotions:
        recent_list = ", ".join(e["emotion"] for e in recent_emotions)
        recent_pattern = (
            f"Recently this user has tended to feel: {recent_list}. "
            "Use this only as soft context, not a label to repeat back to them."
        )

    guidance = EMPATHY_GUIDANCE.get(current_emotion, EMPATHY_GUIDANCE["neutral"])

    return f"""{persona_prompt}

You are emotionally intelligent. Read the user's emotional state and respond like a caring, perceptive human would:
- Listen patiently, never interrupt or rush past what they said.
- Acknowledge their feelings before offering advice or solutions.
- Use encouraging, respectful, non-judgmental language.
- Ask a thoughtful follow-up question when it fits naturally.
- Never pretend to be human, and never diagnose or replace professional mental health help — gently suggest it if things sound serious.

The user's current message reads as: {current_emotion}. {guidance}
{recent_pattern}"""
