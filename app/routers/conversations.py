from datetime import datetime

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models import Conversation, Message, Companion, User
from auth import require_user_api
from schemas import RenameRequest, FlagRequest

router = APIRouter()


def _conversation_summary(c: Conversation) -> dict:
    return {
        "id": c.id,
        "title": c.title or "New conversation",
        "companion_name": c.companion.name,
        "companion_id": c.companion_id,
        "pinned": c.pinned,
        "archived": c.archived,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat() if c.updated_at else c.created_at.isoformat(),
    }


@router.get("/api/conversations")
def list_conversations(
    archived: bool = False, user: User = Depends(require_user_api), db: Session = Depends(get_db)
):
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.archived.is_(archived))
        .order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
        .all()
    )
    return JSONResponse([_conversation_summary(c) for c in conversations])


@router.post("/api/conversations/{conversation_id}/rename")
def rename_conversation(
    conversation_id: str,
    payload: RenameRequest,
    user: User = Depends(require_user_api),
    db: Session = Depends(get_db),
):
    conversation = (
        db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user.id).first()
    )
    if not conversation:
        return JSONResponse({"error": "Not found"}, status_code=404)
    conversation.title = payload.title.strip()[:120] or conversation.title
    db.commit()
    return JSONResponse(_conversation_summary(conversation))


@router.post("/api/conversations/{conversation_id}/pin")
def pin_conversation(
    conversation_id: str,
    payload: FlagRequest,
    user: User = Depends(require_user_api),
    db: Session = Depends(get_db),
):
    conversation = (
        db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user.id).first()
    )
    if not conversation:
        return JSONResponse({"error": "Not found"}, status_code=404)
    conversation.pinned = payload.value
    db.commit()
    return JSONResponse(_conversation_summary(conversation))


@router.post("/api/conversations/{conversation_id}/archive")
def archive_conversation(
    conversation_id: str,
    payload: FlagRequest,
    user: User = Depends(require_user_api),
    db: Session = Depends(get_db),
):
    conversation = (
        db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user.id).first()
    )
    if not conversation:
        return JSONResponse({"error": "Not found"}, status_code=404)
    conversation.archived = payload.value
    db.commit()
    return JSONResponse(_conversation_summary(conversation))


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)
):
    conversation = (
        db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user.id).first()
    )
    if not conversation:
        return JSONResponse({"error": "Not found"}, status_code=404)
    db.delete(conversation)
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/api/conversations/{conversation_id}/export")
def export_conversation(
    conversation_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)
):
    conversation = (
        db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user.id).first()
    )
    if not conversation:
        return JSONResponse({"error": "Not found"}, status_code=404)

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    lines = [f"Conversation: {conversation.title or 'Untitled'}", f"Companion: {conversation.companion.name}", ""]
    for m in messages:
        speaker = "You" if m.role == "user" else conversation.companion.name
        lines.append(f"[{m.created_at.strftime('%Y-%m-%d %H:%M')}] {speaker}: {m.content}")

    content = "\n".join(lines)
    filename = f"conversation-{conversation_id[:8]}.txt"
    return Response(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/search")
def search(q: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    if not q or not q.strip():
        return JSONResponse([])

    like_pattern = f"%{q.strip()}%"

    matches = (
        db.query(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user.id)
        .filter(or_(Message.content.ilike(like_pattern), Conversation.title.ilike(like_pattern)))
        .order_by(Message.created_at.desc())
        .limit(50)
        .all()
    )

    results = []
    for message, conversation in matches:
        content = message.content
        idx = content.lower().find(q.strip().lower())
        snippet = content if idx == -1 else content[max(0, idx - 40) : idx + 80]
        results.append(
            {
                "conversation_id": conversation.id,
                "companion_name": conversation.companion.name,
                "title": conversation.title or "New conversation",
                "message_id": message.id,
                "snippet": snippet,
                "created_at": message.created_at.isoformat(),
            }
        )

    return JSONResponse(results)
