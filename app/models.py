import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; PostgreSQL hands back aware ones. Normalise."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


ROLES = ("user", "admin", "super_admin")
MESSAGE_STATUSES = ("pending", "streaming", "completed", "failed", "cancelled")
JOB_STATUSES = ("queued", "processing", "completed", "failed", "cancelled")
MEMORY_TYPES = (
    "profile",
    "preference",
    "fact",
    "interest",
    "event",
    "relationship",
    "conversation_summary",
    "emotional_context",
)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=new_id)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")  # super_admin | admin | user
    display_name = Column(String, nullable=True)
    emotion_tracking_enabled = Column(Boolean, nullable=False, default=True)
    default_voice_id = Column(  # cleared by privacy.service.delete_voice
        String(36), ForeignKey("voices.id", use_alter=True, name="fk_users_default_voice_id"), nullable=True
    )
    default_language = Column(String, nullable=False, default="auto")
    voice_speed = Column(Float, nullable=False, default=1.0)  # 0.8-1.3 tape-speed multiplier (couples pitch)
    voice_volume_db = Column(Float, nullable=False, default=0.0)  # -6..+6 dB baseline offset
    voice_emotional_intensity = Column(Float, nullable=False, default=1.0)  # 0..1, how strongly presets apply
    voice_style = Column(String, nullable=False, default="casual")  # "formal" | "casual" | "auto"
    voice_auto_adaptive = Column(Boolean, nullable=False, default=True)
    # privacy controls
    memory_enabled = Column(Boolean, nullable=False, default=True)
    store_voice_audio = Column(Boolean, nullable=False, default=True)
    data_retention_days = Column(Integer, nullable=True)  # None = keep until deleted
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    companions = relationship(
        "Companion", back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )
    conversations = relationship(
        "Conversation", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class UserSession(Base):
    """Server-side record of every issued session token, so logout/role changes can revoke it."""

    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    user_agent = Column(String(255), nullable=True)


class Companion(Base):
    __tablename__ = "companions"
    __table_args__ = (Index("ix_companions_public_created", "is_public", "created_at"),)

    id = Column(String(36), primary_key=True, default=new_id)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    persona_prompt = Column(Text, nullable=False)
    avatar_url = Column(String, nullable=True)
    voice_id = Column(String(36), ForeignKey("voices.id"), nullable=True)
    is_public = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=now)

    owner = relationship("User", back_populates="companions")


class Voice(Base):
    __tablename__ = "voices"

    id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, default="other")
    kind = Column(String, nullable=False)  # 'builtin' | 'cloned'
    provider = Column(String(20), nullable=False)  # xtts | f5tts | inworld
    # builtin speaker name (XTTS) / provider voiceId (Inworld). For cloned voices on
    # Inworld this is filled in after the one-time clone registration.
    provider_voice_id = Column(String(255), nullable=True)
    # storage key (relative to DATA_DIR/voice_refs) of the reference recording; never sent to clients
    clone_reference = Column(String(255), nullable=True)
    language = Column(String(16), nullable=True)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="active")  # active | disabled
    consent_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    preview_audio_path = Column(String, nullable=True)  # public URL for builtin previews only
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_archived_updated", "user_id", "archived", "updated_at"),)

    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    companion_id = Column(String(36), ForeignKey("companions.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=True)
    pinned = Column(Boolean, nullable=False, default=False)
    archived = Column(Boolean, nullable=False, default=False)
    # rolling summary of everything older than the recent-message window
    summary = Column(Text, nullable=True)
    summarized_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    user = relationship("User", back_populates="conversations")
    companion = relationship("Companion")
    messages = relationship(
        "Message",
        back_populates="conversation",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id = Column(String(36), primary_key=True, default=new_id)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="completed")  # see MESSAGE_STATUSES
    error_code = Column(String(64), nullable=True)
    emotion = Column(String, nullable=True)  # detected user emotion (Emotional Conversation Module)
    emotion_confidence = Column(Float, nullable=True)
    response_strategy = Column(String(32), nullable=True)  # assistant strategy chosen for this turn
    language = Column(String, nullable=True)  # detected/used language code
    model = Column(String(120), nullable=True)  # LLM that produced an assistant message
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    conversation = relationship("Conversation", back_populates="messages")
    voice_message = relationship(
        "VoiceMessage", back_populates="message", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )


class VoiceMessage(Base):
    __tablename__ = "voice_messages"

    id = Column(String(36), primary_key=True, default=new_id)
    message_id = Column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    audio_path = Column(String, nullable=False)  # relative to DATA_DIR
    voice_id = Column(String(36), ForeignKey("voices.id"), nullable=True, index=True)
    tts_style = Column(String, nullable=True)  # emotion or voice-changer preset applied
    duration_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=now, index=True)

    message = relationship("Message", back_populates="voice_message")


class EmotionalMemory(Base):
    __tablename__ = "emotional_memory"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    recent_emotions = Column(JSON, nullable=False, default=list)  # [{"emotion": "sad", "at": "..."}]
    updated_at = Column(DateTime(timezone=True), default=now)


class Memory(Base):
    """Long-term memory about a user. Written only by the extraction pipeline, never
    blindly from raw messages (see memory/extraction.py)."""

    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_user_type", "user_id", "type"),
        Index("ix_memories_user_expires", "user_id", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    companion_id = Column(String(36), ForeignKey("companions.id", ondelete="CASCADE"), nullable=True)
    type = Column(String(32), nullable=False)  # see MEMORY_TYPES
    content = Column(Text, nullable=False)
    importance = Column(Float, nullable=False, default=0.5)  # 0..1
    confidence = Column(Float, nullable=False, default=0.5)  # 0..1
    source_message_id = Column(String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)


class Job(Base):
    """Background work (TTS, summaries, memory extraction, retention). The table is the
    queue: workers claim a row by flipping queued -> processing in one UPDATE."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_queue_status_run_after", "queue", "status", "run_after"),)

    id = Column(String(36), primary_key=True, default=new_id)
    kind = Column(String(40), nullable=False)
    queue = Column(String(20), nullable=False, default="default")
    status = Column(String(16), nullable=False, default="queued")  # see JOB_STATUSES
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(String(500), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=1)
    dedupe_key = Column(String(200), nullable=True, index=True)
    locked_by = Column(String(100), nullable=True)
    run_after = Column(DateTime(timezone=True), default=now, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_target", "target_type", "target_id"),)

    id = Column(String(36), primary_key=True, default=new_id)
    actor_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_email = Column(String(320), nullable=True)  # snapshot, survives actor deletion
    action = Column(String(64), nullable=False)
    target_type = Column(String(32), nullable=False)
    target_id = Column(String(64), nullable=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    request_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False, index=True)
