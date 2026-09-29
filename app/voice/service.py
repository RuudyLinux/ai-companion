"""
TTS work that runs inside the job worker (never in a web request): resolving which
voice/reference to use, calling the engine, applying the DSP delivery chain and storing
the result. Also voice-clone reference storage.
"""

import logging
import os
import uuid

import requests
from sqlalchemy.orm import Session

from core import storage
from core.config import settings
from jobs.queue import JobError
from models import Conversation, Job, Message, User, Voice, VoiceMessage
from voice.adaptive import resolve_adaptive_effect, resolve_scaled_chain
from voice.audio_utils import audio_duration_seconds, convert_to_wav
from voice.effects import EMOTION_EFFECTS, VOICE_CHANGER_STYLES, apply_chain
from voice.engine import get_engine
from voice.engine_base import VoiceEngine

log = logging.getLogger("app.voice")

PREVIEW_TEXT = "Hello, this is a preview of my voice."
VALID_EFFECTS = set(EMOTION_EFFECTS) | set(VOICE_CHANGER_STYLES)


def is_valid_effect(effect: str | None) -> bool:
    return effect in (None, "", "auto") or effect in VALID_EFFECTS


def _voice_usable_by(voice: Voice | None, user_id: str) -> bool:
    if voice is None or voice.status != "active":
        return False
    return voice.owner_id is None or voice.owner_id == user_id


def synthesis_kwargs(db: Session, engine: VoiceEngine, voice: Voice) -> dict:
    """Maps a Voice row onto the engine's speaker_wav / speaker_name arguments."""
    if voice.kind != "cloned":
        return {"speaker_name": voice.provider_voice_id}

    if voice.provider == engine.name and voice.provider_voice_id and not engine.clone_needs_raw_file:
        return {"speaker_name": voice.provider_voice_id}

    reference = storage.resolve(voice.clone_reference)
    if reference is None or not reference.exists():
        raise JobError("VOICE_REFERENCE_MISSING", "The recording for this cloned voice is missing.")

    if engine.clone_needs_raw_file:
        return {"speaker_wav": str(reference)}

    # server-side cloning engine (Inworld): register once, then reuse the provider id
    try:
        provider_voice_id = engine.register_clone(str(reference), voice.language or "en", voice.name)
    except requests.RequestException as exc:
        raise JobError("VOICE_CLONE_FAILED", "The voice provider couldn't clone this voice.", retryable=True) from exc
    voice.provider, voice.provider_voice_id = engine.name, provider_voice_id
    db.commit()
    return {"speaker_name": provider_voice_id}


def _synthesize(engine: VoiceEngine, text: str, out_path: str, language: str, kwargs: dict) -> None:
    try:
        engine.synthesize(text, out_path, language=language, **kwargs)
    except JobError:
        raise
    except requests.RequestException as exc:
        raise JobError("TTS_PROVIDER_ERROR", "The voice provider failed to generate audio.", retryable=True) from exc
    except Exception as exc:
        log.exception("tts engine failed", extra={"voice_engine": engine.name, "error_code": "TTS_FAILED"})
        raise JobError("TTS_FAILED", "Voice generation failed.") from exc


def render_message_audio(db: Session, job: Job) -> dict:
    payload = job.payload or {}
    message = (
        db.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Message.id == payload.get("message_id"), Conversation.user_id == job.user_id)
        .first()
    )
    if message is None or not message.content.strip():
        raise JobError("MESSAGE_NOT_FOUND", "The message no longer exists.")
    user = db.get(User, job.user_id)
    voice = db.get(Voice, payload.get("voice_id"))
    if user is None or not _voice_usable_by(voice, user.id):
        raise JobError("VOICE_NOT_FOUND", "The requested voice was not found.")

    engine = get_engine()
    language = message.language or "en"
    kwargs = synthesis_kwargs(db, engine, voice)

    effect = payload.get("tts_effect")
    if effect == "auto" and user.voice_auto_adaptive:
        prior_user_msg = (
            db.query(Message)
            .filter(
                Message.conversation_id == message.conversation_id,
                Message.role == "user",
                Message.created_at < message.created_at,
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        effect_key = resolve_adaptive_effect(
            assistant_reply_text=message.content,
            user_emotion=prior_user_msg.emotion if prior_user_msg else None,
            persona_prompt=message.conversation.companion.persona_prompt,
            formal_casual=user.voice_style,
        )
    else:
        effect_key = None if effect in (None, "", "auto") else effect

    settings.voice_audio_dir.mkdir(parents=True, exist_ok=True)
    raw_path = settings.data_dir / "tmp" / f"{job.id}_raw.wav"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    # new file name per render so a client holding the old URL never gets half-written audio
    final_path = settings.voice_audio_dir / f"{message.id}-{uuid.uuid4().hex[:8]}.wav"
    try:
        _synthesize(engine, message.content, str(raw_path), language, kwargs)
        chain = resolve_scaled_chain(
            effect_key,
            intensity=user.voice_emotional_intensity,
            speed_bias=user.voice_speed,
            volume_bias_db=user.voice_volume_db,
        )
        if chain:
            apply_chain(str(raw_path), str(final_path), chain)
        else:
            os.replace(raw_path, final_path)
        duration = audio_duration_seconds(str(final_path))
    except Exception:
        final_path.unlink(missing_ok=True)
        raise
    finally:
        raw_path.unlink(missing_ok=True)

    key = storage.to_key(final_path)
    existing = db.query(VoiceMessage).filter(VoiceMessage.message_id == message.id).first()
    old_key = None
    if existing:
        old_key = existing.audio_path
        existing.audio_path, existing.voice_id = key, voice.id
        existing.tts_style, existing.duration_seconds = effect_key, duration
        voice_message = existing
    else:
        voice_message = VoiceMessage(
            message_id=message.id, audio_path=key, voice_id=voice.id, tts_style=effect_key, duration_seconds=duration
        )
        db.add(voice_message)
    db.commit()
    if old_key and old_key != key:
        storage.delete(old_key)

    return {
        "voice_message_id": voice_message.id,
        "audio_url": f"/media/voice/{voice_message.id}",
        "duration": duration,
        "tts_style": effect_key,
    }


def render_voice_preview(db: Session, job: Job) -> dict:
    voice = db.get(Voice, (job.payload or {}).get("voice_id"))
    if not _voice_usable_by(voice, job.user_id):
        raise JobError("VOICE_NOT_FOUND", "The requested voice was not found.")
    engine = get_engine()
    kwargs = synthesis_kwargs(db, engine, voice)
    settings.voice_previews_dir.mkdir(parents=True, exist_ok=True)
    final_path = preview_path(voice)
    tmp_path = settings.data_dir / "tmp" / f"{job.id}_preview.wav"
    try:
        _synthesize(engine, PREVIEW_TEXT, str(tmp_path), voice.language or "en", kwargs)
        os.replace(tmp_path, final_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"audio_url": f"/api/voices/{voice.id}/preview"}


def preview_path(voice: Voice):
    return settings.voice_previews_dir / f"{voice.id}.wav"


def store_clone_reference(source_path: str, voice_id: str) -> str:
    """Normalises an uploaded recording to WAV under DATA_DIR/voice_refs; returns the storage key."""
    settings.voice_refs_dir.mkdir(parents=True, exist_ok=True)
    target = settings.voice_refs_dir / f"{voice_id}.wav"
    convert_to_wav(source_path, str(target))
    return storage.to_key(target)


def delete_voice_files(voice: Voice) -> None:
    storage.delete(voice.clone_reference)
    preview_path(voice).unlink(missing_ok=True)
