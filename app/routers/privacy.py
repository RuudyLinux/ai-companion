"""Self-service data controls: export, memory management, bulk deletion, account deletion."""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from auth import clear_session_cookie, require_user, require_user_api, verify_password
from core import audit
from core.errors import AppError, NotFound
from core.rate_limit import rate_limit
from database import get_db
from models import Conversation, Memory, User, as_utc
from privacy.service import delete_account, delete_conversations, export_user_data
from schemas import DeleteAccountRequest, MemoryUpdate

router = APIRouter()


class MemoryNotFound(NotFound):
    code = "MEMORY_NOT_FOUND"
    message = "The requested memory was not found."


def _memory_view(m: Memory) -> dict:
    return {
        "id": m.id,
        "type": m.type,
        "content": m.content,
        "importance": m.importance,
        "confidence": m.confidence,
        "created_at": as_utc(m.created_at).isoformat() if m.created_at else None,
        "expires_at": as_utc(m.expires_at).isoformat() if m.expires_at else None,
    }


def _owned_memory(db: Session, user: User, memory_id: str) -> Memory:
    memory = db.query(Memory).filter(Memory.id == memory_id, Memory.user_id == user.id).first()
    if memory is None:
        raise MemoryNotFound()
    return memory


@router.get("/api/me/export")
def export_my_data(
    user: User = Depends(require_user_api),
    _limit: None = Depends(rate_limit("export")),
    db: Session = Depends(get_db),
):
    body = json.dumps(export_user_data(db, user), ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="ai-companion-export.json"', "Cache-Control": "no-store"},
    )


@router.get("/api/me/memories")
def list_memories(user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    memories = db.query(Memory).filter(Memory.user_id == user.id).order_by(Memory.updated_at.desc()).limit(500).all()
    return [_memory_view(m) for m in memories]


@router.patch("/api/me/memories/{memory_id}")
def edit_memory(
    memory_id: str, payload: MemoryUpdate, user: User = Depends(require_user_api), db: Session = Depends(get_db)
):
    memory = _owned_memory(db, user, memory_id)
    memory.content = payload.content
    if payload.type:
        memory.type = payload.type
    memory.confidence = 1.0  # the user said so
    db.commit()
    return _memory_view(memory)


@router.delete("/api/me/memories/{memory_id}")
def delete_memory(memory_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    db.delete(_owned_memory(db, user, memory_id))
    db.commit()
    return {"ok": True}


@router.delete("/api/me/memories")
def delete_all_memories(user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    deleted = db.query(Memory).filter(Memory.user_id == user.id).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "deleted": deleted}


@router.delete("/api/me/conversations")
def delete_all_conversations(user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    conversations = db.query(Conversation).filter(Conversation.user_id == user.id).all()
    return {"ok": True, "deleted": delete_conversations(db, conversations)}


def _check_account_deletion(db: Session, user: User, password: str, confirm: str) -> None:
    DeleteAccountRequest(password=password, confirm=confirm)  # raises ValidationError -> 422
    if not verify_password(password, user.hashed_password):
        raise AppError("Password is incorrect.", code="INVALID_PASSWORD", status_code=403)
    if user.role == "super_admin" and db.query(User).filter(User.role == "super_admin").count() == 1:
        raise AppError(
            "You are the last super admin. Promote someone else before deleting your account.",
            code="LAST_SUPER_ADMIN",
            status_code=409,
        )


@router.post("/settings/delete-account")
def delete_my_account_form(
    request: Request,
    password: str = Form(..., max_length=256),
    confirm: str = Form(..., max_length=20),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    try:
        _check_account_deletion(db, user, password, confirm)
    except AppError as exc:
        return RedirectResponse(f"/settings?notice={exc.code.lower()}", status_code=303)
    except ValueError:  # pydantic ValidationError subclasses ValueError
        return RedirectResponse("/settings?notice=confirm-required", status_code=303)
    audit.record(db, actor=user, action="account.delete", target_type="user", target_id=user.id, request=request)
    delete_account(db, user)
    response = RedirectResponse("/login?message=Your+account+and+data+were+deleted.", status_code=303)
    clear_session_cookie(response)
    return response
