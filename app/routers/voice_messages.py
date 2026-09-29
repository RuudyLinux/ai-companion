import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from models import VoiceMessage, Message, Conversation, User
from auth import require_user_api

router = APIRouter()


def _owned_voice_message(db: Session, voice_message_id: str, user_id: str) -> VoiceMessage | None:
    return (
        db.query(VoiceMessage)
        .join(Message, VoiceMessage.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(VoiceMessage.id == voice_message_id, Conversation.user_id == user_id)
        .first()
    )


@router.get("/api/voice-messages")
def list_voice_messages(user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    rows = (
        db.query(VoiceMessage, Message, Conversation)
        .join(Message, VoiceMessage.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user.id)
        .order_by(VoiceMessage.created_at.desc())
        .all()
    )
    return JSONResponse(
        [
            {
                "id": vm.id,
                "message_id": msg.id,
                "conversation_id": conv.id,
                "companion_name": conv.companion.name,
                "text_preview": msg.content[:100],
                "tts_style": vm.tts_style,
                "duration_seconds": vm.duration_seconds,
                "created_at": vm.created_at.isoformat(),
                "audio_url": f"/media/voice/{vm.id}",
            }
            for vm, msg, conv in rows
        ]
    )


@router.get("/media/voice/{voice_message_id}")
def serve_voice_audio(voice_message_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    vm = _owned_voice_message(db, voice_message_id, user.id)
    if not vm or not os.path.exists(vm.audio_path):
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(vm.audio_path, media_type="audio/wav")


@router.get("/api/voice-messages/{voice_message_id}/download")
def download_voice_audio(voice_message_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    vm = _owned_voice_message(db, voice_message_id, user.id)
    if not vm or not os.path.exists(vm.audio_path):
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(
        vm.audio_path,
        media_type="audio/wav",
        filename=f"voice-message-{voice_message_id[:8]}.wav",
    )


@router.get("/api/voice-messages/{voice_message_id}/share")
def share_voice_audio(voice_message_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    vm = _owned_voice_message(db, voice_message_id, user.id)
    if not vm:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse({"url": f"/media/voice/{voice_message_id}"})


@router.delete("/api/voice-messages/{voice_message_id}")
def delete_voice_message(voice_message_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    vm = _owned_voice_message(db, voice_message_id, user.id)
    if not vm:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if os.path.exists(vm.audio_path):
        os.unlink(vm.audio_path)
    db.delete(vm)
    db.commit()
    return JSONResponse({"ok": True})
