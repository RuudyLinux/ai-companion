"""Speech APIs: text-to-speech jobs, speech-to-text, and job status/cancellation."""

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth import require_user_api
from core.access import get_message_for_user, get_voice_for_user
from core.errors import AppError, NotFound
from core.rate_limit import rate_limit
from core.uploads import validated_audio_upload
from database import get_db
from jobs.queue import cancel, enqueue, job_view
from models import Job, User, VoiceMessage
from schemas import SpeakRequest
from voice.engine import get_engine
from voice.language import display_name_for
from voice.service import is_valid_effect
from voice.stt_runner import run_transcription

router = APIRouter()


class JobNotFound(NotFound):
    code = "JOB_NOT_FOUND"
    message = "The requested job was not found."


def _get_job_for_user(db: Session, user: User, job_id: str) -> Job:
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if job is None:
        raise JobNotFound()
    return job


@router.post("/api/messages/{message_id}/speak")
def speak_message(
    message_id: str,
    payload: SpeakRequest,
    user: User = Depends(require_user_api),
    _limit: None = Depends(rate_limit("tts")),
    db: Session = Depends(get_db),
):
    """Queues TTS for an assistant message. Returns 200 with the audio when a matching
    clip already exists, otherwise 202 with a job to poll at /api/jobs/{job_id}."""
    message = get_message_for_user(db, user, message_id)
    if message.role != "assistant" or message.status not in ("completed", "cancelled") or not message.content.strip():
        raise AppError("Only finished assistant replies can be spoken.", code="MESSAGE_NOT_SPEAKABLE", status_code=409)
    voice = get_voice_for_user(db, user, payload.voice_id)
    if not is_valid_effect(payload.tts_effect):
        raise AppError("Unknown voice effect.", code="INVALID_EFFECT", status_code=422)

    engine = get_engine()
    lang_code = message.language or "en"
    if not engine.supports_language(lang_code):
        return {
            "status": "skipped",
            "skipped": True,
            "reason": f"No voice available for {display_name_for(lang_code)} — text reply only.",
        }

    existing = db.query(VoiceMessage).filter(VoiceMessage.message_id == message.id).first()
    if (
        existing
        and payload.tts_effect != "auto"
        and existing.tts_style == (payload.tts_effect or None)
        and existing.voice_id == voice.id
    ):
        return {
            "status": "completed",
            "skipped": False,
            "audio_url": f"/media/voice/{existing.id}",
            "duration": existing.duration_seconds,
        }

    job = enqueue(
        db,
        "tts_message",
        {"message_id": message.id, "voice_id": voice.id, "tts_effect": payload.tts_effect},
        queue="tts",
        user_id=user.id,
        dedupe_key=f"tts:{message.id}:{voice.id}:{payload.tts_effect}",
        max_attempts=2,
    )
    db.commit()
    return JSONResponse({"status": job.status, "job_id": job.id, "skipped": False}, status_code=202)


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    return job_view(_get_job_for_user(db, user, job_id))


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    job = _get_job_for_user(db, user, job_id)
    cancel(db, job)
    db.refresh(job)
    return job_view(job)


@router.post("/api/stt")
async def api_stt(
    audio: UploadFile = File(...),
    user: User = Depends(require_user_api),
    _limit: None = Depends(rate_limit("stt")),
):
    async with validated_audio_upload(audio) as upload:
        result = await run_in_threadpool(run_transcription, upload.path)
    return {"text": result["text"], "language": result["language"], "duration": round(upload.duration_seconds, 2)}
