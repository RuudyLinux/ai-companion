from pydantic import BaseModel


class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class CompanionCreateRequest(BaseModel):
    name: str
    description: str
    is_public: bool = False


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    preferred_language: str | None = None  # display name from voice.language.LANGUAGES, None = auto-detect


class SpeakRequest(BaseModel):
    message_id: str
    voice_id: str
    tts_effect: str | None = None  # emotion or voice-changer preset name, None = neutral


class RoleUpdateRequest(BaseModel):
    user_id: str
    role: str


class RenameRequest(BaseModel):
    title: str


class FlagRequest(BaseModel):
    value: bool
