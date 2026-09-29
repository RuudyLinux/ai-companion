from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from auth import require_user, require_user_api
from core import storage
from core.errors import NotFound
from database import get_db
from models import Conversation, Message, User, VoiceMessage, as_utc
from privacy.service import delete_voice_message
from templating import templates

router = APIRouter()


class VoiceMessageNotFound(NotFound):
    code = "VOICE_MESSAGE_NOT_FOUND"
    message = "The requested voice message was not found."


def _owned_voice_message(db: Session, voice_message_id: str, user_id: str) -> VoiceMessage:
    vm = (
        db.query(VoiceMessage)
        .join(Message, VoiceMessage.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(VoiceMessage.id == voice_message_id, Conversation.user_id == user_id)
        .first()
    )
    if vm is None:
        raise VoiceMessageNotFound()
    return vm


def _audio_file(vm: VoiceMessage):
    path = storage.resolve(vm.audio_path)
    if path is None or not path.exists():
        raise VoiceMessageNotFound("The audio file for this message is no longer available.")
    return path


@router.get("/voice-history")
def voice_history(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(request, "voice_history.html", {"user": user})


@router.get("/api/voice-messages")
def list_voice_messages(user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    rows = (
        db.query(VoiceMessage, Message, Conversation)
        .join(Message, VoiceMessage.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user.id)
        .order_by(VoiceMessage.created_at.desc())
        .limit(500)
        .all()
    )
    return [
        {
            "id": vm.id,
            "message_id": msg.id,
            "conversation_id": conv.id,
            "companion_name": conv.companion.name,
            "text_preview": msg.content[:100],
            "tts_style": vm.tts_style,
            "duration_seconds": vm.duration_seconds,
            "created_at": as_utc(vm.created_at).isoformat(),
            "audio_url": f"/media/voice/{vm.id}",
        }
        for vm, msg, conv in rows
    ]


@router.get("/media/voice/{voice_message_id}")
def serve_voice_audio(voice_message_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    vm = _owned_voice_message(db, voice_message_id, user.id)
    return FileResponse(_audio_file(vm), media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/api/voice-messages/{voice_message_id}/download")
def download_voice_audio(voice_message_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    vm = _owned_voice_message(db, voice_message_id, user.id)
    return FileResponse(_audio_file(vm), media_type="audio/wav", filename=f"voice-message-{voice_message_id[:8]}.wav")


@router.get("/api/voice-messages/{voice_message_id}/share")
def share_voice_audio(voice_message_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    """The link only works for the owner's own signed-in session; it is not a public share."""
    vm = _owned_voice_message(db, voice_message_id, user.id)
    return {"url": f"/media/voice/{vm.id}"}


@router.delete("/api/voice-messages/{voice_message_id}")
def delete_voice_message_route(
    voice_message_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)
):
    delete_voice_message(db, _owned_voice_message(db, voice_message_id, user.id))
    return {"ok": True}
