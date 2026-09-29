import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Boolean, Text, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship

from database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=new_id)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")  # super_admin | admin | user
    display_name = Column(String, nullable=True)
    emotion_tracking_enabled = Column(Boolean, nullable=False, default=True)
    default_voice_id = Column(String(36), ForeignKey("voices.id"), nullable=True)
    default_language = Column(String, nullable=False, default="auto")
    voice_speed = Column(Float, nullable=False, default=1.0)  # 0.8-1.3 tape-speed multiplier (couples pitch)
    voice_volume_db = Column(Float, nullable=False, default=0.0)  # -6..+6 dB baseline offset
    voice_emotional_intensity = Column(Float, nullable=False, default=1.0)  # 0..1, how strongly presets apply
    voice_style = Column(String, nullable=False, default="casual")  # "formal" | "casual" | "auto"
    voice_auto_adaptive = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=now)

    companions = relationship("Companion", back_populates="owner")
    conversations = relationship("Conversation", back_populates="user")


class Companion(Base):
    __tablename__ = "companions"

    id = Column(String(36), primary_key=True, default=new_id)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    persona_prompt = Column(Text, nullable=False)
    avatar_url = Column(String, nullable=True)
    voice_id = Column(String(36), ForeignKey("voices.id"), nullable=True)
    is_public = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)

    owner = relationship("User", back_populates="companions")


class Voice(Base):
    __tablename__ = "voices"

    id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, default="other")
    kind = Column(String, nullable=False)  # 'builtin' | 'cloned'
    speaker_ref = Column(String, nullable=False)  # XTTS speaker name, or path to reference wav
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    preview_audio_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=now)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    companion_id = Column(String(36), ForeignKey("companions.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=True)
    pinned = Column(Boolean, nullable=False, default=False)
    archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    user = relationship("User", back_populates="conversations")
    companion = relationship("Companion")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=new_id)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    emotion = Column(String, nullable=True)  # detected user emotion (Emotional Conversation Module)
    language = Column(String, nullable=True)  # detected/used language code
    created_at = Column(DateTime, default=now)

    conversation = relationship("Conversation", back_populates="messages")
    voice_message = relationship("VoiceMessage", back_populates="message", uselist=False)


class VoiceMessage(Base):
    __tablename__ = "voice_messages"

    id = Column(String(36), primary_key=True, default=new_id)
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True)
    audio_path = Column(String, nullable=False)
    voice_id = Column(String(36), ForeignKey("voices.id"), nullable=True)
    tts_style = Column(String, nullable=True)  # emotion or voice-changer preset applied
    duration_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime, default=now)

    message = relationship("Message", back_populates="voice_message")


class EmotionalMemory(Base):
    __tablename__ = "emotional_memory"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    recent_emotions = Column(JSON, nullable=False, default=list)  # [{"emotion": "sad", "at": "..."}]
    updated_at = Column(DateTime, default=now)
