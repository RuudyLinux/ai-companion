from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from auth import require_user, require_user_api
from core import storage
from core.access import get_owned_voice, get_voice_for_user, list_voices_for_user
from core.config import settings
from core.errors import AppError, NotFound
from core.rate_limit import rate_limit
from core.uploads import validated_audio_upload
from database import get_db
from jobs.queue import enqueue
from models import User, Voice, new_id, now
from privacy.service import delete_voice
from templating import templates
from voice.language import LANGUAGES
from voice.service import preview_path, store_clone_reference

router = APIRouter()

MAX_CLONED_VOICES_PER_USER = 10
MAX_CLONE_SECONDS = 60


class PreviewNotReady(NotFound):
    code = "PREVIEW_NOT_READY"
    message = "This voice preview hasn't been generated yet."


def voice_view(voice: Voice) -> dict:
    """Client-safe voice description: no reference paths, no provider internals."""
    return {
        "id": voice.id,
        "name": voice.name,
        "category": voice.category,
        "kind": voice.kind,
        "language": voice.language,
        "owned": voice.owner_id is not None,
    }


@router.get("/voices")
def voice_library(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    voices = list_voices_for_user(db, user)
    return templates.TemplateResponse(
        request,
        "voice_library.html",
        {
            "user": user,
            "voices": voices,
            "languages": LANGUAGES,
            "max_clone_seconds": MAX_CLONE_SECONDS,
            "min_clone_seconds": settings.min_clone_audio_seconds,
        },
    )


@router.get("/api/voices")
def list_voices(user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    return [voice_view(v) for v in list_voices_for_user(db, user)]


@router.post("/api/voices/{voice_id}/preview")
def request_preview(
    voice_id: str,
    user: User = Depends(require_user_api),
    _limit: None = Depends(rate_limit("tts")),
    db: Session = Depends(get_db),
):
    """Returns the preview URL if it exists; otherwise queues generation (202 + job id).
    Previews are generated once per voice and cached — Inworld is a paid API."""
    voice = get_voice_for_user(db, user, voice_id)
    if voice.kind == "builtin" and voice.preview_audio_path and voice.preview_audio_path.startswith("/static/"):
        return {"status": "completed", "audio_url": voice.preview_audio_path}
    if preview_path(voice).exists():
        return {"status": "completed", "audio_url": f"/api/voices/{voice.id}/preview"}
    job = enqueue(
        db,
        "tts_preview",
        {"voice_id": voice.id},
        queue="tts",
        user_id=user.id,
        dedupe_key=f"preview:{voice.id}:{user.id}",
    )
    db.commit()
    return JSONResponse({"status": job.status, "job_id": job.id}, status_code=202)


@router.get("/api/voices/{voice_id}/preview")
def get_preview(voice_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    voice = get_voice_for_user(db, user, voice_id)
    path = preview_path(voice)
    if not path.exists():
        raise PreviewNotReady()
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/api/voices/clone", status_code=201)
async def clone_voice(
    name: str = Form(..., min_length=1, max_length=60),
    language: str = Form("English", max_length=40),
    consent: bool = Form(...),
    audio: UploadFile = File(...),
    user: User = Depends(require_user_api),
    _limit: None = Depends(rate_limit("voice_clone")),
    db: Session = Depends(get_db),
):
    """Creates a private cloned voice from a recording of the user's own voice."""
    if not consent:
        raise AppError(
            "You must confirm this is your voice or that you have the speaker's permission.",
            code="CONSENT_REQUIRED",
            status_code=422,
        )
    if language not in LANGUAGES:
        raise AppError("Unsupported language.", code="INVALID_LANGUAGE", status_code=422)
    owned = db.query(Voice).filter(Voice.owner_id == user.id).count()
    if owned >= MAX_CLONED_VOICES_PER_USER:
        raise AppError(
            f"You can have at most {MAX_CLONED_VOICES_PER_USER} cloned voices.", code="VOICE_LIMIT", status_code=409
        )

    voice_id = new_id()
    async with validated_audio_upload(
        audio, max_seconds=MAX_CLONE_SECONDS, min_seconds=settings.min_clone_audio_seconds
    ) as upload:
        reference_key = await run_in_threadpool(store_clone_reference, upload.path, voice_id)

    voice = Voice(
        id=voice_id,
        name=name.strip(),
        category="cloned",
        kind="cloned",
        provider=settings.voice_engine,
        clone_reference=reference_key,
        language=LANGUAGES[language][0],
        owner_id=user.id,
        consent_confirmed_at=now(),
    )
    db.add(voice)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(reference_key)
        raise
    return voice_view(voice)


@router.delete("/api/voices/{voice_id}")
def remove_voice(voice_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    voice = get_owned_voice(db, user, voice_id)
    delete_voice(db, voice)
    return {"ok": True}
