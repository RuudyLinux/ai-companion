from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import require_user_api
from core.access import get_conversation_for_user
from database import get_db
from models import Conversation, Message, User, as_utc
from privacy.service import delete_conversations
from schemas import FlagRequest, RenameRequest

router = APIRouter()


def _conversation_summary(c: Conversation) -> dict:
    created = as_utc(c.created_at)
    updated = as_utc(c.updated_at) or created
    return {
        "id": c.id,
        "title": c.title or "New conversation",
        "companion_name": c.companion.name,
        "companion_id": c.companion_id,
        "pinned": c.pinned,
        "archived": c.archived,
        "created_at": created.isoformat(),
        "updated_at": updated.isoformat(),
    }


@router.get("/api/conversations")
def list_conversations(archived: bool = False, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.archived.is_(archived))
        .order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
        .limit(500)
        .all()
    )
    return [_conversation_summary(c) for c in conversations]


@router.post("/api/conversations/{conversation_id}/rename")
def rename_conversation(
    conversation_id: str, payload: RenameRequest, user: User = Depends(require_user_api), db: Session = Depends(get_db)
):
    conversation = get_conversation_for_user(db, user, conversation_id)
    conversation.title = payload.title
    db.commit()
    return _conversation_summary(conversation)


@router.post("/api/conversations/{conversation_id}/pin")
def pin_conversation(
    conversation_id: str, payload: FlagRequest, user: User = Depends(require_user_api), db: Session = Depends(get_db)
):
    conversation = get_conversation_for_user(db, user, conversation_id)
    conversation.pinned = payload.value
    db.commit()
    return _conversation_summary(conversation)


@router.post("/api/conversations/{conversation_id}/archive")
def archive_conversation(
    conversation_id: str, payload: FlagRequest, user: User = Depends(require_user_api), db: Session = Depends(get_db)
):
    conversation = get_conversation_for_user(db, user, conversation_id)
    conversation.archived = payload.value
    db.commit()
    return _conversation_summary(conversation)


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    """Deletes the conversation, its messages, generated audio rows and the audio files."""
    delete_conversations(db, [get_conversation_for_user(db, user, conversation_id)])
    return {"ok": True}


@router.get("/api/conversations/{conversation_id}/export")
def export_conversation(conversation_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    conversation = get_conversation_for_user(db, user, conversation_id)
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.content != "")
        .order_by(Message.created_at.asc())
        .all()
    )

    lines = [f"Conversation: {conversation.title or 'Untitled'}", f"Companion: {conversation.companion.name}", ""]
    for m in messages:
        speaker = "You" if m.role == "user" else conversation.companion.name
        lines.append(f"[{m.created_at.strftime('%Y-%m-%d %H:%M')}] {speaker}: {m.content}")

    filename = f"conversation-{conversation.id[:8]}.txt"
    return Response(
        content="\n".join(lines),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/search")
def search(
    q: str = Query("", max_length=200), user: User = Depends(require_user_api), db: Session = Depends(get_db)
):
    term = q.strip()
    if not term:
        return []
    # escape LIKE wildcards so "%" or "_" in a query are matched literally
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like_pattern = f"%{escaped}%"

    matches = (
        db.query(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user.id)
        .filter(
            or_(
                Message.content.ilike(like_pattern, escape="\\"),
                Conversation.title.ilike(like_pattern, escape="\\"),
            )
        )
        .order_by(Message.created_at.desc())
        .limit(50)
        .all()
    )

    results = []
    for message, conversation in matches:
        content = message.content
        idx = content.lower().find(term.lower())
        snippet = content if idx == -1 else content[max(0, idx - 40) : idx + 80]
        results.append(
            {
                "conversation_id": conversation.id,
                "companion_name": conversation.companion.name,
                "title": conversation.title or "New conversation",
                "message_id": message.id,
                "snippet": snippet[:200],
                "created_at": as_utc(message.created_at).isoformat(),
            }
        )
    return results
