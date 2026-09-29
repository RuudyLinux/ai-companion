"""
Ownership/visibility rules in one place. Every route that takes a resource ID from the
client must load it through one of these helpers, never with a bare `.filter(id == ...)`.
"""

from sqlalchemy import and_, or_
from sqlalchemy.orm import Query, Session

from core.config import settings
from core.errors import NotFound
from models import Companion, Conversation, Message, User, Voice


class CompanionNotFound(NotFound):
    code = "COMPANION_NOT_FOUND"
    message = "The requested companion was not found."


class ConversationNotFound(NotFound):
    code = "CONVERSATION_NOT_FOUND"
    message = "The requested conversation was not found."


class MessageNotFound(NotFound):
    code = "MESSAGE_NOT_FOUND"
    message = "The requested message was not found."


class VoiceNotFound(NotFound):
    code = "VOICE_NOT_FOUND"
    message = "The requested voice was not found."


def visible_companions(db: Session, user: User) -> Query:
    return db.query(Companion).filter(or_(Companion.owner_id == user.id, Companion.is_public.is_(True)))


def get_companion_for_user(db: Session, user: User, companion_id: str) -> Companion:
    """Private companions are only visible to their owner. Not-found and not-allowed look
    identical so IDs of private companions can't be probed."""
    companion = visible_companions(db, user).filter(Companion.id == companion_id).first()
    if companion is None:
        raise CompanionNotFound()
    return companion


def get_conversation_for_user(db: Session, user: User, conversation_id: str) -> Conversation:
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .first()
    )
    if conversation is None:
        raise ConversationNotFound()
    return conversation


def get_message_for_user(db: Session, user: User, message_id: str) -> Message:
    message = (
        db.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Message.id == message_id, Conversation.user_id == user.id)
        .first()
    )
    if message is None:
        raise MessageNotFound()
    return message


def accessible_voices(db: Session, user: User) -> Query:
    """Builtin voices of the active engine, plus the user's own active cloned voices.
    Other users' cloned voices are never visible or usable."""
    engine = settings.voice_engine
    return db.query(Voice).filter(
        Voice.status == "active",
        or_(
            and_(Voice.kind == "builtin", Voice.owner_id.is_(None), Voice.provider == engine),
            and_(
                Voice.kind == "cloned",
                Voice.owner_id == user.id,
                or_(Voice.provider == engine, Voice.clone_reference.isnot(None)),
            ),
        ),
    )


def list_voices_for_user(db: Session, user: User) -> list[Voice]:
    return accessible_voices(db, user).order_by(Voice.kind.desc(), Voice.category, Voice.name).all()


def get_voice_for_user(db: Session, user: User, voice_id: str) -> Voice:
    voice = accessible_voices(db, user).filter(Voice.id == voice_id).first()
    if voice is None:
        raise VoiceNotFound()
    return voice


def get_owned_voice(db: Session, user: User, voice_id: str) -> Voice:
    voice = db.query(Voice).filter(Voice.id == voice_id, Voice.owner_id == user.id).first()
    if voice is None:
        raise VoiceNotFound()
    return voice
