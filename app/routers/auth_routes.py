from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import (
    clear_session_cookie,
    create_session,
    current_session_id,
    get_current_user,
    hash_password,
    revoke_session,
    set_session_cookie,
    verify_password_or_dummy,
)
from core.rate_limit import check_rate_limit, rate_limit
from database import get_db
from models import User
from schemas import LoginRequest, SignupRequest
from templating import templates

router = APIRouter()


def _redirect_with_error(path: str, message: str) -> RedirectResponse:
    return RedirectResponse(f"{path}?error={quote_plus(message)}", status_code=303)


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    field = err["loc"][0] if err.get("loc") else "input"
    if field == "email":
        return "Please enter a valid email address."
    if field == "password":
        return err["msg"].replace("String", "Password").replace("Value error, ", "")
    return "Invalid input."


def _signed_in_response(db: Session, user: User, request: Request) -> RedirectResponse:
    # a fresh session id on every login: any pre-login session value becomes useless
    old_sid = current_session_id(request)
    if old_sid:
        revoke_session(db, old_sid)
    token = create_session(db, user, request)
    response = RedirectResponse("/companions", status_code=303)
    set_session_cookie(response, token)
    return response


@router.get("/login")
def login_page(request: Request, error: str | None = None, message: str | None = None, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/companions", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": error, "message": message})


@router.post("/login", dependencies=[Depends(rate_limit("login"))])
def login_submit(
    request: Request,
    email: str = Form(..., max_length=320),
    password: str = Form(..., max_length=256),
    db: Session = Depends(get_db),
):
    try:
        creds = LoginRequest(email=email, password=password)
    except ValidationError:
        return _redirect_with_error("/login", "Invalid email or password")

    # per-account limit on top of the per-IP one, against distributed guessing
    check_rate_limit("login", f"email:{creds.email}")

    user = db.query(User).filter(func.lower(User.email) == creds.email).first()
    if not verify_password_or_dummy(creds.password, user):
        return _redirect_with_error("/login", "Invalid email or password")
    return _signed_in_response(db, user, request)


@router.get("/signup")
def signup_page(request: Request, error: str | None = None, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/companions", status_code=303)
    return templates.TemplateResponse(request, "signup.html", {"error": error})


@router.post("/signup", dependencies=[Depends(rate_limit("signup"))])
def signup_submit(
    request: Request,
    email: str = Form(..., max_length=320),
    password: str = Form(..., max_length=256),
    db: Session = Depends(get_db),
):
    try:
        data = SignupRequest(email=email, password=password)
    except ValidationError as exc:
        return _redirect_with_error("/signup", _first_error(exc))

    if db.query(User).filter(func.lower(User.email) == data.email).first():
        return _redirect_with_error("/signup", "An account with that email already exists")

    user = User(email=data.email, hashed_password=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two signups racing for the same email
        db.rollback()
        return _redirect_with_error("/signup", "An account with that email already exists")
    return _signed_in_response(db, user, request)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    session_id = current_session_id(request)
    if session_id:
        revoke_session(db, session_id)
        db.commit()
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    return response
