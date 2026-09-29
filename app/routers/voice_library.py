from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Voice, User
from auth import require_user, require_user_api
from voice.engine import get_engine
from templating import templates

router = APIRouter()

PREVIEW_DIR = Path(__file__).resolve().parent.parent / "static" / "previews"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_TEXT = "Hello, this is a preview of my voice."


@router.get("/voices")
def voice_library(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    voices = db.query(Voice).order_by(Voice.kind.desc(), Voice.category, Voice.name).all()
    return templates.TemplateResponse(request, "voice_library.html", {"user": user, "voices": voices})


@router.post("/api/voices/{voice_id}/preview")
def preview_voice(voice_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    voice = db.query(Voice).filter(Voice.id == voice_id).first()
    if not voice:
        return JSONResponse({"error": "Voice not found"}, status_code=404)

    # generated once per voice, on first preview click, then reused — Inworld is a paid
    # API, so we don't want to regenerate the same preview clip on every click.
    preview_path = PREVIEW_DIR / f"{voice.id}.wav"
    if not preview_path.exists():
        engine = get_engine()
        kwargs = {"language": "en"}
        if voice.kind == "cloned" and engine.clone_needs_raw_file:
            kwargs["speaker_wav"] = voice.speaker_ref
        else:
            kwargs["speaker_name"] = voice.speaker_ref
        engine.synthesize(PREVIEW_TEXT, str(preview_path), **kwargs)
        voice.preview_audio_path = f"/static/previews/{preview_path.name}"
        db.commit()

    return FileResponse(preview_path, media_type="audio/wav")


@router.get("/voice-history")
def voice_history(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(request, "voice_history.html", {"user": user})
