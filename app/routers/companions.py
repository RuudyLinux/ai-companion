from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models import Companion, User
from auth import require_user
from templating import templates

router = APIRouter()


@router.get("/companions")
def companions_list(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    companions = (
        db.query(Companion)
        .filter(or_(Companion.owner_id == user.id, Companion.is_public.is_(True)))
        .order_by(Companion.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request, "companions.html", {"user": user, "companions": companions}
    )


@router.get("/companions/new")
def companion_new_page(request: Request, error: str | None = None, user: User = Depends(require_user)):
    return templates.TemplateResponse(request, "companion_new.html", {"user": user, "error": error})


@router.post("/companions/new")
def companion_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(...),
    is_public: bool = Form(False),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    persona_prompt = (
        f"You are {name}. {description}\n\n"
        "Stay in character. Be warm, engaging, and consistent with this persona in every reply."
    )
    companion = Companion(owner_id=user.id, name=name, persona_prompt=persona_prompt, is_public=is_public)
    db.add(companion)
    db.commit()
    db.refresh(companion)

    return RedirectResponse(f"/chat/{companion.id}", status_code=303)
