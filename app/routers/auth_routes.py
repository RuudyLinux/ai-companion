from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User
from auth import hash_password, verify_password, create_session_token, get_current_user, COOKIE_NAME
from templating import templates

router = APIRouter()


@router.get("/login")
def login_page(request: Request, error: str | None = None, message: str | None = None, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/companions", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": error, "message": message})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return RedirectResponse("/login?error=Invalid+email+or+password", status_code=303)

    token = create_session_token(user.id)
    response = RedirectResponse("/companions", status_code=303)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return response


@router.get("/signup")
def signup_page(request: Request, error: str | None = None, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/companions", status_code=303)
    return templates.TemplateResponse(request, "signup.html", {"error": error})


@router.post("/signup")
def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if len(password) < 6:
        return RedirectResponse("/signup?error=Password+must+be+at+least+6+characters", status_code=303)

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return RedirectResponse("/signup?error=An+account+with+that+email+already+exists", status_code=303)

    user = User(email=email, hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_session_token(user.id)
    response = RedirectResponse("/companions", status_code=303)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response
