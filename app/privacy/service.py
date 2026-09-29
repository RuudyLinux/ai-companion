"""
Data export and deletion. Deleting always goes: collect file keys -> delete rows ->
commit -> delete files, so a failed transaction never leaves rows pointing at files that
are already gone, and a committed delete never leaves sensitive audio behind.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from core import storage
from models import (
    Companion,
    Conversation,
    EmotionalMemory,
    Job,
    Memory,
    Message,
    User,
    UserSession,
    Voice,
    VoiceMessage,
    as_utc,
    now,
)
from voice.service import delete_voice_files

VOICE_AUDIO_TTL_WHEN_NOT_STORED = timedelta(hours=1)
FINISHED_JOB_TTL = timedelta(days=7)
DEAD_SESSION_TTL = timedelta(days=30)


def _iso(value):
    value = as_utc(value)
    return value.isoformat() if value else None


def voice_keys_for_conversations(db: Session, conversation_ids: list[str]) -> list[str]:
    if not conversation_ids:
        return []
    rows = (
        db.query(VoiceMessage.audio_path)
        .join(Message, VoiceMessage.message_id == Message.id)
        .filter(Message.conversation_id.in_(conversation_ids))
        .all()
    )
    return [path for (path,) in rows]


def delete_conversations(db: Session, conversations: list[Conversation]) -> int:
    ids = [c.id for c in conversations]
    keys = voice_keys_for_conversations(db, ids)
    for conversation in conversations:
        db.delete(conversation)
    db.commit()
    for key in keys:
        storage.delete(key)
    return len(ids)


def delete_voice_message(db: Session, voice_message: VoiceMessage) -> None:
    key = voice_message.audio_path
    db.delete(voice_message)
    db.commit()
    storage.delete(key)


def delete_voice(db: Session, voice: Voice) -> None:
    """Removes a cloned voice, its reference recording, preview, and every audio clip made with it."""
    clips = db.query(VoiceMessage).filter(VoiceMessage.voice_id == voice.id).all()
    keys = [clip.audio_path for clip in clips]
    for clip in clips:
        db.delete(clip)
    db.flush()  # no ORM relationship links clips to voices, so force the child deletes first
    db.query(User).filter(User.default_voice_id == voice.id).update({User.default_voice_id: None})
    db.query(Companion).filter(Companion.voice_id == voice.id).update({Companion.voice_id: None})
    db.delete(voice)
    db.commit()
    for key in keys:
        storage.delete(key)
    delete_voice_files(voice)


def delete_account(db: Session, user: User) -> None:
    db.flush()  # write pending rows (e.g. the audit entry naming this user) before the user row goes
    conversation_ids = [cid for (cid,) in db.query(Conversation.id).filter(Conversation.user_id == user.id).all()]
    keys = voice_keys_for_conversations(db, conversation_ids)
    voices = db.query(Voice).filter(Voice.owner_id == user.id).all()
    # other users' conversations with this user's public companions go too (FK cascade);
    # their audio files must be collected before the rows disappear
    companion_ids = [cid for (cid,) in db.query(Companion.id).filter(Companion.owner_id == user.id).all()]
    if companion_ids:
        foreign_conversations = [
            cid
            for (cid,) in db.query(Conversation.id).filter(Conversation.companion_id.in_(companion_ids)).all()
            if cid not in conversation_ids
        ]
        keys += voice_keys_for_conversations(db, foreign_conversations)
    db.delete(user)  # FK cascades remove sessions, companions, conversations, messages, memories, voices, jobs
    db.commit()
    for key in keys:
        storage.delete(key)
    for voice in voices:
        delete_voice_files(voice)


def export_user_data(db: Session, user: User) -> dict:
    conversations = db.query(Conversation).filter(Conversation.user_id == user.id).all()
    emotional = db.get(EmotionalMemory, user.id)
    return {
        "exported_at": _iso(now()),
        "account": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "display_name": user.display_name,
            "created_at": _iso(user.created_at),
            "settings": {
                "emotion_tracking_enabled": user.emotion_tracking_enabled,
                "memory_enabled": user.memory_enabled,
                "store_voice_audio": user.store_voice_audio,
                "data_retention_days": user.data_retention_days,
                "default_language": user.default_language,
                "voice_speed": user.voice_speed,
                "voice_volume_db": user.voice_volume_db,
                "voice_emotional_intensity": user.voice_emotional_intensity,
                "voice_style": user.voice_style,
                "voice_auto_adaptive": user.voice_auto_adaptive,
            },
        },
        "companions": [
            {"id": c.id, "name": c.name, "persona_prompt": c.persona_prompt, "is_public": c.is_public}
            for c in db.query(Companion).filter(Companion.owner_id == user.id).all()
        ],
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "companion_id": c.companion_id,
                "created_at": _iso(c.created_at),
                "summary": c.summary,
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "status": m.status,
                        "emotion": m.emotion,
                        "language": m.language,
                        "created_at": _iso(m.created_at),
                    }
                    for m in c.messages
                ],
            }
            for c in conversations
        ],
        "memories": [
            {
                "id": m.id,
                "type": m.type,
                "content": m.content,
                "importance": m.importance,
                "confidence": m.confidence,
                "created_at": _iso(m.created_at),
                "expires_at": _iso(m.expires_at),
            }
            for m in db.query(Memory).filter(Memory.user_id == user.id).all()
        ],
        "emotional_history": emotional.recent_emotions if emotional else [],
        "voices": [
            {"id": v.id, "name": v.name, "provider": v.provider, "language": v.language, "created_at": _iso(v.created_at)}
            for v in db.query(Voice).filter(Voice.owner_id == user.id).all()
        ],
    }


def run_retention(db: Session) -> dict:
    """Periodic privacy/data hygiene sweep (run by the worker)."""
    current = now()
    stats = {"conversations": 0, "voice_messages": 0, "memories": 0, "jobs": 0, "sessions": 0}

    for user in db.query(User).filter(User.data_retention_days.isnot(None)).all():
        cutoff = current - timedelta(days=user.data_retention_days)
        expired = (
            db.query(Conversation).filter(Conversation.user_id == user.id, Conversation.updated_at < cutoff).all()
        )
        if expired:
            stats["conversations"] += delete_conversations(db, expired)

    audio_cutoff = current - VOICE_AUDIO_TTL_WHEN_NOT_STORED
    transient_clips = (
        db.query(VoiceMessage)
        .join(Message, VoiceMessage.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .join(User, Conversation.user_id == User.id)
        .filter(User.store_voice_audio.is_(False), VoiceMessage.created_at < audio_cutoff)
        .all()
    )
    for clip in transient_clips:
        delete_voice_message(db, clip)
        stats["voice_messages"] += 1

    stats["memories"] = (
        db.query(Memory).filter(Memory.expires_at.isnot(None), Memory.expires_at < current).delete(synchronize_session=False)
    )
    stats["jobs"] = (
        db.query(Job)
        .filter(Job.status.in_(("completed", "failed", "cancelled")), Job.created_at < current - FINISHED_JOB_TTL)
        .delete(synchronize_session=False)
    )
    stats["sessions"] = (
        db.query(UserSession)
        .filter(UserSession.expires_at < current - DEAD_SESSION_TTL)
        .delete(synchronize_session=False)
    )
    db.commit()
    return stats

