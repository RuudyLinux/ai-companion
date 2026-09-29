from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from auth import require_user
from core.access import visible_companions
from database import get_db
from models import Companion, User
from schemas import CompanionCreateRequest
from templating import templates

router = APIRouter()


@router.get("/companions")
def companions_list(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    companions = visible_companions(db, user).order_by(Companion.created_at.desc()).all()
    return templates.TemplateResponse(request, "companions.html", {"user": user, "companions": companions})


@router.get("/companions/new")
def companion_new_page(request: Request, error: str | None = None, user: User = Depends(require_user)):
    return templates.TemplateResponse(request, "companion_new.html", {"user": user, "error": error})


@router.post("/companions/new")
def companion_create(
    name: str = Form(..., max_length=200),
    description: str = Form(..., max_length=8000),
    is_public: bool = Form(False),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    try:
        data = CompanionCreateRequest(name=name, description=description, is_public=is_public)
    except ValidationError:
        message = "Name must be 1-80 characters and the description 1-4000 characters."
        return RedirectResponse(f"/companions/new?error={quote_plus(message)}", status_code=303)

    persona_prompt = (
        f"You are {data.name}. {data.description}\n\n"
        "Stay in character. Be warm, engaging, and consistent with this persona in every reply."
    )
    companion = Companion(owner_id=user.id, name=data.name, persona_prompt=persona_prompt, is_public=data.is_public)
    db.add(companion)
    db.commit()

    return RedirectResponse(f"/chat/{companion.id}", status_code=303)
