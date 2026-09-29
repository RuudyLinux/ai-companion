from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User, Voice
from auth import require_user
from templating import templates

router = APIRouter()


@router.get("/settings")
def settings_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    voices = db.query(Voice).order_by(Voice.kind.desc(), Voice.category, Voice.name).all()
    return templates.TemplateResponse(request, "settings.html", {"user": user, "voices": voices})


@router.post("/settings/emotion-toggle")
def toggle_emotion_tracking(
    enabled: bool = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    user.emotion_tracking_enabled = enabled
    db.commit()
    return RedirectResponse("/settings", status_code=303)


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
    user.default_voice_id = default_voice_id or None
    user.voice_speed = max(0.8, min(1.3, voice_speed))
    user.voice_volume_db = max(-6.0, min(6.0, voice_volume_db))
    user.voice_emotional_intensity = max(0.0, min(1.0, voice_emotional_intensity))
    user.voice_style = voice_style if voice_style in ("formal", "casual", "auto") else "casual"
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/voice-auto-adaptive-toggle")
def toggle_voice_auto_adaptive(
    enabled: bool = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    user.voice_auto_adaptive = enabled
    db.commit()
    return RedirectResponse("/settings", status_code=303)
