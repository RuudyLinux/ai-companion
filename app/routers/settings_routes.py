from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from auth import require_user
from core.access import get_voice_for_user, list_voices_for_user
from database import get_db
from models import Memory, User
from schemas import PrivacySettings, VoicePreferences
from templating import templates

router = APIRouter()


def _back(notice: str | None = None) -> RedirectResponse:
    return RedirectResponse(f"/settings?notice={notice}" if notice else "/settings", status_code=303)


@router.get("/settings")
def settings_page(
    request: Request, notice: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    memory_count = db.query(Memory).filter(Memory.user_id == user.id).count()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"user": user, "voices": list_voices_for_user(db, user), "memory_count": memory_count, "notice": notice},
    )


@router.post("/settings/emotion-toggle")
def toggle_emotion_tracking(enabled: bool = Form(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    user.emotion_tracking_enabled = enabled
    db.commit()
    return _back()


@router.post("/settings/voice-preferences")
def update_voice_preferences(
    default_voice_id: str = Form(""),
    voice_speed: float = Form(1.0),
    voice_volume_db: float = Form(0.0),
    voice_emotional_intensity: float = Form(1.0),
    voice_style: str = Form("casual"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    try:
        prefs = VoicePreferences(
            default_voice_id=default_voice_id or None,
            voice_speed=voice_speed,
            voice_volume_db=voice_volume_db,
            voice_emotional_intensity=voice_emotional_intensity,
            voice_style=voice_style,
        )
    except ValidationError:
        return _back("invalid-voice-preferences")
    if prefs.default_voice_id:
        get_voice_for_user(db, user, prefs.default_voice_id)  # 404 for voices the user can't use

    user.default_voice_id = prefs.default_voice_id
    user.voice_speed = prefs.voice_speed
    user.voice_volume_db = prefs.voice_volume_db
    user.voice_emotional_intensity = prefs.voice_emotional_intensity
    user.voice_style = prefs.voice_style
    db.commit()
    return _back("saved")


@router.post("/settings/voice-auto-adaptive-toggle")
def toggle_voice_auto_adaptive(
    enabled: bool = Form(...), user: User = Depends(require_user), db: Session = Depends(get_db)
):
    user.voice_auto_adaptive = enabled
    db.commit()
    return _back()


@router.post("/settings/privacy")
def update_privacy(
    memory_enabled: bool = Form(False),
    store_voice_audio: bool = Form(False),
    data_retention_days: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    try:
        privacy = PrivacySettings(
            memory_enabled=memory_enabled,
            store_voice_audio=store_voice_audio,
            data_retention_days=int(data_retention_days) if data_retention_days.strip() else None,
        )
    except (ValidationError, ValueError):
        return _back("invalid-retention")
    user.memory_enabled = privacy.memory_enabled
    user.store_voice_audio = privacy.store_voice_audio
    user.data_retention_days = privacy.data_retention_days
    db.commit()
    return _back("saved")
