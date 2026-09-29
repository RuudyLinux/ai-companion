from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from auth import require_role, revoke_all_sessions
from core import audit
from core.errors import AppError, NotFound
from database import get_db
from models import AuditLog, Companion, User, Voice
from privacy.service import delete_voice
from schemas import RoleUpdateRequest
from templating import templates

router = APIRouter()


@router.get("/admin")
def admin_home(request: Request, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "user_count": db.query(User).count(),
            "companion_count": db.query(Companion).count(),
            "public_companions": db.query(Companion)
            .filter(Companion.is_public.is_(True))
            .order_by(Companion.created_at.desc())
            .limit(100)
            .all(),
        },
    )


@router.get("/admin/roles")
def admin_roles(request: Request, user: User = Depends(require_role("super_admin")), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at.asc()).all()
    return templates.TemplateResponse(request, "admin_roles.html", {"user": user, "users": users})


@router.post("/admin/roles/update")
def update_role(
    request: Request,
    user_id: str = Form(...),
    role: str = Form(...),
    user: User = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
):
    try:
        data = RoleUpdateRequest(user_id=user_id, role=role)
    except ValidationError:
        return RedirectResponse("/admin/roles?error=invalid", status_code=303)
    if data.user_id == user.id:
        # can't change your own role: prevents accidental self-demotion/lock-out
        return RedirectResponse("/admin/roles?error=self", status_code=303)

    target = db.get(User, data.user_id)
    if target is None:
        return RedirectResponse("/admin/roles?error=not-found", status_code=303)
    if target.role == data.role:
        return RedirectResponse("/admin/roles", status_code=303)

    before = {"role": target.role}
    target.role = data.role
    # privileges changed: force the target to sign in again with the new role
    revoke_all_sessions(db, target.id)
    audit.record(
        db,
        actor=user,
        action="user.role_change",
        target_type="user",
        target_id=target.id,
        before=before,
        after={"role": data.role},
        request=request,
    )
    db.commit()
    return RedirectResponse("/admin/roles", status_code=303)


@router.get("/admin/audit")
def audit_log_page(request: Request, user: User = Depends(require_role("super_admin")), db: Session = Depends(get_db)):
    entries = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(200).all()
    return templates.TemplateResponse(request, "admin_audit.html", {"user": user, "entries": entries})


@router.post("/api/admin/companions/{companion_id}/unpublish")
def unpublish_companion(
    companion_id: str,
    request: Request,
    user: User = Depends(require_role("admin", api=True)),
    db: Session = Depends(get_db),
):
    """Moderation: hide a public companion from everyone except its owner."""
    companion = db.get(Companion, companion_id)
    if companion is None:
        raise NotFound(code="COMPANION_NOT_FOUND", message="The requested companion was not found.")
    if not companion.is_public:
        raise AppError("That companion is already private.", code="ALREADY_PRIVATE", status_code=409)
    companion.is_public = False
    audit.record(
        db,
        actor=user,
        action="companion.unpublish",
        target_type="companion",
        target_id=companion.id,
        before={"is_public": True, "name": companion.name, "owner_id": companion.owner_id},
        after={"is_public": False},
        request=request,
    )
    db.commit()
    return {"ok": True}


@router.delete("/api/admin/voices/{voice_id}")
def moderate_delete_voice(
    voice_id: str,
    request: Request,
    user: User = Depends(require_role("admin", api=True)),
    db: Session = Depends(get_db),
):
    """Moderation: remove any cloned voice (e.g. reported as non-consensual)."""
    voice = db.query(Voice).filter(Voice.id == voice_id, Voice.kind == "cloned").first()
    if voice is None:
        raise NotFound(code="VOICE_NOT_FOUND", message="The requested voice was not found.")
    audit.record(
        db,
        actor=user,
        action="voice.delete",
        target_type="voice",
        target_id=voice.id,
        before={"name": voice.name, "owner_id": voice.owner_id, "provider": voice.provider},
        request=request,
    )
    delete_voice(db, voice)  # commits the audit row together with the deletion
    return {"ok": True}
