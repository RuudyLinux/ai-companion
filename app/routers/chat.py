import tempfile
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Companion, Conversation, Message, User, Voice, VoiceMessage, now as utcnow
from auth import require_user, require_user_api
from llm.openrouter import stream_reply
from emotion.classifier import classify_emotion
from emotion.guidance import build_empathy_system_prompt, get_recent_emotions, record_emotion
from voice.effects import EMOTION_EFFECTS, VOICE_CHANGER_STYLES, apply_chain
from voice.adaptive import resolve_adaptive_effect, resolve_scaled_chain
from voice.engine import get_engine
from voice.audio_utils import audio_duration_seconds
from voice.language import detect_language, display_name_for, code_for_name, LANGUAGES
from schemas import ChatRequest, SpeakRequest
from templating import templates

router = APIRouter()

VOICE_AUDIO_DIR = Path(__file__).resolve().parent.parent / "data" / "voice_audio"
VOICE_AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def _get_or_create_conversation(db: Session, user_id: str, companion_id: str) -> Conversation:
    conversation = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id, Conversation.companion_id == companion_id, Conversation.archived.is_(False))
        .order_by(Conversation.updated_at.desc())
        .first()
    )
    if not conversation:
        conversation = Conversation(user_id=user_id, companion_id=companion_id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    return conversation


def _render_chat(request: Request, user: User, companion: Companion, conversation: Conversation, db: Session):
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
        .all()
    )
    voices = db.query(Voice).order_by(Voice.kind.desc(), Voice.category, Voice.name).all()

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "user": user,
            "companion": companion,
            "conversation": conversation,
            "messages": messages,
            "voices": voices,
            "emotions": list(EMOTION_EFFECTS.keys()),
            "styles": list(VOICE_CHANGER_STYLES.keys()),
            "languages": list(LANGUAGES.keys()),
        },
    )


@router.get("/chat/{companion_id}")
def chat_page(
    request: Request, companion_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    companion = db.query(Companion).filter(Companion.id == companion_id).first()
    if not companion:
        return HTMLResponse("Companion not found", status_code=404)

    conversation = _get_or_create_conversation(db, user.id, companion_id)
    return _render_chat(request, user, companion, conversation, db)


@router.post("/chat/{companion_id}/new")
def new_chat_thread(companion_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    conversation = Conversation(user_id=user.id, companion_id=companion_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return RedirectResponse(f"/chat/conversation/{conversation.id}", status_code=303)


@router.get("/chat/conversation/{conversation_id}")
def open_conversation(
    request: Request, conversation_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .first()
    )
    if not conversation:
        return HTMLResponse("Conversation not found", status_code=404)

    return _render_chat(request, user, conversation.companion, conversation, db)


@router.post("/api/chat")
def api_chat(
    request: Request,
    payload: ChatRequest,
    user: User = Depends(require_user_api),
    db: Session = Depends(get_db),
):
    conversation_id = payload.conversation_id
    message = payload.message.strip()
    if not conversation_id or not message:
        return JSONResponse({"error": "conversation_id and message are required"}, status_code=400)

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .first()
    )
    if not conversation:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    persona_prompt = conversation.companion.persona_prompt

    forced_lang = code_for_name(payload.preferred_language) if payload.preferred_language else None

    # detect_language returns None for short/ambiguous text (e.g. "Hello" alone can
    # misdetect as almost anything) — fall back to this conversation's last known
    # language rather than guessing, and only default to English if there's no history.
    last_message = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id, Message.language.isnot(None))
        .order_by(Message.created_at.desc())
        .first()
    )
    fallback_lang = last_message.language if last_message else "en"

    detected_lang = forced_lang or detect_language(message) or fallback_lang
    lang_name = display_name_for(detected_lang)

    user_message = Message(conversation_id=conversation_id, role="user", content=message, language=detected_lang)
    db.add(user_message)
    db.commit()

    # auto-title new conversations from the first message
    if not conversation.title:
        conversation.title = message[:60] + ("..." if len(message) > 60 else "")
        db.commit()

    system_prompt = persona_prompt
    if user.emotion_tracking_enabled:
        emotion = classify_emotion(message)
        recent = get_recent_emotions(db, user.id)
        system_prompt = build_empathy_system_prompt(persona_prompt, emotion, recent)
        user_message.emotion = emotion
        db.commit()
        record_emotion(db, user.id, emotion)

    if forced_lang:
        system_prompt += (
            f"\n\nIMPORTANT: regardless of what language this message is written in, "
            f"you must reply entirely in {lang_name}. Do not use English or any other language."
        )
    else:
        system_prompt += f"\n\nThe user is writing in {lang_name}. Reply fluently in {lang_name}, matching their language."

    history = [
        {"role": m.role, "content": m.content}
        for m in db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    ]

    assistant_message = Message(conversation_id=conversation_id, role="assistant", content="", language=detected_lang)
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)

    def generate():
        full_reply = []
        try:
            for chunk in stream_reply(system_prompt, history):
                full_reply.append(chunk)
                yield chunk
        finally:
            text = "".join(full_reply).strip()
            assistant_message.content = text or "[no reply generated]"
            conversation.updated_at = utcnow()
            db.commit()

    return StreamingResponse(
        generate(), media_type="text/plain", headers={"X-Assistant-Message-Id": assistant_message.id}
    )


@router.post("/api/messages/{message_id}/speak")
def speak_message(
    message_id: str,
    payload: SpeakRequest,
    user: User = Depends(require_user_api),
    db: Session = Depends(get_db),
):
    message = (
        db.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Message.id == message_id, Conversation.user_id == user.id)
        .first()
    )
    if not message:
        return JSONResponse({"error": "Message not found"}, status_code=404)

    existing = db.query(VoiceMessage).filter(VoiceMessage.message_id == message_id).first()
    if (
        existing
        and payload.tts_effect != "auto"
        and existing.tts_style == payload.tts_effect
        and existing.voice_id == payload.voice_id
    ):
        return JSONResponse(
            {"audio_url": f"/media/voice/{existing.id}", "duration": existing.duration_seconds, "skipped": False}
        )

    voice = db.query(Voice).filter(Voice.id == payload.voice_id).first()
    if not voice:
        return JSONResponse({"error": "Voice not found"}, status_code=404)

    engine = get_engine()
    lang_code = message.language or "en"
    if not engine.supports_language(lang_code):
        return JSONResponse(
            {
                "skipped": True,
                "reason": f"No {engine.name} voice for {display_name_for(message.language)} — text reply only.",
            }
        )

    raw_path = VOICE_AUDIO_DIR / f"{message_id}_raw.wav"
    final_path = VOICE_AUDIO_DIR / f"{message_id}.wav"

    kwargs = {"language": lang_code}
    if voice.kind == "cloned" and engine.clone_needs_raw_file:
        kwargs["speaker_wav"] = voice.speaker_ref
    else:
        kwargs["speaker_name"] = voice.speaker_ref

    engine.synthesize(message.content, str(raw_path), **kwargs)

    if payload.tts_effect == "auto" and user.voice_auto_adaptive:
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
            user_message_text=prior_user_msg.content if prior_user_msg else None,
            persona_prompt=message.conversation.companion.persona_prompt,
            formal_casual=user.voice_style,
        )
    else:
        effect_key = None if payload.tts_effect == "auto" else payload.tts_effect

    chain = resolve_scaled_chain(
        effect_key,
        intensity=user.voice_emotional_intensity,
        speed_bias=user.voice_speed,
        volume_bias_db=user.voice_volume_db,
    )
    if chain:
        apply_chain(str(raw_path), str(final_path), chain)
        os.unlink(raw_path)
    else:
        os.replace(raw_path, final_path)

    duration = audio_duration_seconds(str(final_path))

    if existing:
        existing.audio_path = str(final_path)
        existing.voice_id = voice.id
        existing.tts_style = effect_key
        existing.duration_seconds = duration
        db.commit()
        voice_message_id = existing.id
    else:
        vm = VoiceMessage(
            message_id=message_id,
            audio_path=str(final_path),
            voice_id=voice.id,
            tts_style=effect_key,
            duration_seconds=duration,
        )
        db.add(vm)
        db.commit()
        db.refresh(vm)
        voice_message_id = vm.id

    return JSONResponse({"audio_url": f"/media/voice/{voice_message_id}", "duration": duration, "skipped": False})


TRANSCRIBE_CLI = Path(__file__).resolve().parent.parent / "scripts" / "transcribe_cli.py"


@router.post("/api/stt")
async def api_stt(audio: UploadFile = File(...), user: User = Depends(require_user_api)):
    suffix = os.path.splitext(audio.filename or "audio.webm")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        # subprocess isolation: ctranslate2 (faster-whisper) and torch (XTTS) crash
        # if loaded in the same process — see transcribe_cli.py for the full reason.
        result = subprocess.run(
            [sys.executable, str(TRANSCRIBE_CLI), tmp_path],
            capture_output=True,
            timeout=120,
        )
        text = result.stdout.decode("utf-8", errors="replace").strip()
    finally:
        os.unlink(tmp_path)

    return JSONResponse({"text": text})
