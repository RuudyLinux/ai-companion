from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User, Companion
from auth import require_role
from templating import templates

router = APIRouter()

ASSIGNABLE_ROLES = {"user", "admin", "super_admin"}


@router.get("/admin")
def admin_home(request: Request, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    user_count = db.query(User).count()
    companion_count = db.query(Companion).count()
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"user": user, "user_count": user_count, "companion_count": companion_count},
    )


@router.get("/admin/roles")
def admin_roles(
    request: Request, user: User = Depends(require_role("super_admin")), db: Session = Depends(get_db)
):
    users = db.query(User).order_by(User.created_at.asc()).all()
    return templates.TemplateResponse(request, "admin_roles.html", {"user": user, "users": users})


@router.post("/admin/roles/update")
def update_role(
    user_id: str = Form(...),
    role: str = Form(...),
    user: User = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
):
    if role not in ASSIGNABLE_ROLES:
        return RedirectResponse("/admin/roles", status_code=303)
    if user_id == user.id:
        return RedirectResponse("/admin/roles", status_code=303)  # can't change your own role

    target = db.query(User).filter(User.id == user_id).first()
    if target:
        target.role = role
        db.commit()

    return RedirectResponse("/admin/roles", status_code=303)
