from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from auth import PASSWORD_MAX_BYTES, PASSWORD_MIN_LENGTH
from core.config import settings
from models import MEMORY_TYPES, ROLES

# UUID4 string ids everywhere; validating the shape rejects junk before any DB lookup
EntityId = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F-]{36}$")]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class SignupRequest(Credentials):
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=256)

    @field_validator("password")
    @classmethod
    def _bcrypt_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
            raise ValueError(f"Password must be at most {PASSWORD_MAX_BYTES} bytes")
        return value


class LoginRequest(Credentials):
    pass


class CompanionCreateRequest(StrictModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    is_public: bool = False


class ChatRequest(StrictModel):
    conversation_id: EntityId
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    preferred_language: str | None = Field(default=None, max_length=40)

    @field_validator("message")
    @classmethod
    def _message_length(cls, value: str) -> str:
        if len(value) > settings.max_message_chars:
            raise ValueError(f"Message must be at most {settings.max_message_chars} characters")
        return value


class RegenerateRequest(StrictModel):
    conversation_id: EntityId
    preferred_language: str | None = Field(default=None, max_length=40)


class SpeakRequest(StrictModel):
    # message_id is in the URL; accepted in the body only for backward compatibility
    message_id: EntityId | None = None
    voice_id: EntityId
    tts_effect: str | None = Field(default=None, max_length=40)  # preset name, "auto", or None = neutral


class RoleUpdateRequest(StrictModel):
    user_id: EntityId
    role: str

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError("Unknown role")
        return value


class RenameRequest(StrictModel):
    title: Title


class FlagRequest(StrictModel):
    value: bool


class VoicePreferences(StrictModel):
    default_voice_id: EntityId | None = None
    voice_speed: float = Field(default=1.0, ge=0.8, le=1.3)
    voice_volume_db: float = Field(default=0.0, ge=-6.0, le=6.0)
    voice_emotional_intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    voice_style: str = Field(default="casual", pattern="^(formal|casual|auto)$")


class PrivacySettings(StrictModel):
    memory_enabled: bool
    store_voice_audio: bool
    data_retention_days: int | None = Field(default=None, ge=1, le=3650)


class MemoryUpdate(StrictModel):
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    type: str | None = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str | None) -> str | None:
        if value is not None and value not in MEMORY_TYPES:
            raise ValueError("Unknown memory type")
        return value


class DeleteAccountRequest(StrictModel):
    password: str = Field(min_length=1, max_length=256)
    confirm: str = Field(pattern="^DELETE$")
