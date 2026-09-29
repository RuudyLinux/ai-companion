"""
Chat pages and the streaming chat API.

Reply stream protocol (application/x-ndjson, one JSON object per line):
    {"type": "start", "message_id": "...", "model": "..."}
    {"type": "delta", "text": "..."}                         (repeated)
    {"type": "done", "status": "completed" | "cancelled", "message_id": "..."}
    {"type": "error", "code": "...", "message": "...", "message_id": "..."}   (mid-stream failure)
Failures before the first token are returned as a normal JSON error response instead.
"""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from auth import require_user, require_user_api
from conversation import streams
from conversation.context import build_context
from conversation.summary import maybe_enqueue_summary
from core import storage
from core.access import (
    get_companion_for_user,
    get_conversation_for_user,
    get_message_for_user,
    list_voices_for_user,
)
from core.errors import AppError, Conflict
from core.rate_limit import rate_limit
from database import get_db, session_scope
from emotion.classifier import EmotionResult, detect_emotion
from emotion.guidance import build_emotion_context, get_recent_emotions, record_emotion
from emotion.strategy import strategy_for
from jobs.queue import enqueue
from llm.openrouter import LLMError, StreamResult, stream_reply
from memory.extraction import worth_extracting
from models import Companion, Conversation, Message, User, now
from schemas import ChatRequest, RegenerateRequest
from templating import templates
from voice.effects import EMOTION_EFFECTS, VOICE_CHANGER_STYLES
from voice.language import LANGUAGES, code_for_name, detect_language, display_name_for

log = logging.getLogger("app.chat")

router = APIRouter()


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
    return conversation


def _render_chat(request: Request, user: User, companion: Companion, conversation: Conversation, db: Session):
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "user": user,
            "companion": companion,
            "conversation": conversation,
            "messages": messages,
            "voices": list_voices_for_user(db, user),
            "emotions": list(EMOTION_EFFECTS.keys()),
            "styles": list(VOICE_CHANGER_STYLES.keys()),
            "languages": list(LANGUAGES.keys()),
        },
    )


@router.get("/chat/{companion_id}")
def chat_page(request: Request, companion_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    companion = get_companion_for_user(db, user, companion_id)
    conversation = _get_or_create_conversation(db, user.id, companion.id)
    return _render_chat(request, user, companion, conversation, db)


@router.post("/chat/{companion_id}/new")
def new_chat_thread(companion_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    companion = get_companion_for_user(db, user, companion_id)
    conversation = Conversation(user_id=user.id, companion_id=companion.id)
    db.add(conversation)
    db.commit()
    return RedirectResponse(f"/chat/conversation/{conversation.id}", status_code=303)


@router.get("/chat/conversation/{conversation_id}")
def open_conversation(
    request: Request, conversation_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    conversation = get_conversation_for_user(db, user, conversation_id)
    return _render_chat(request, user, conversation.companion, conversation, db)


# ---------------------------------------------------------------- streaming


def _language_for(db: Session, conversation: Conversation, text: str, preferred: str | None) -> tuple[str, bool]:
    """Returns (language code, forced). detect_language returns None for short/ambiguous
    text (e.g. "Hello" alone can misdetect as almost anything) — fall back to this
    conversation's last known language rather than guessing, else English."""
    forced = code_for_name(preferred) if preferred else None
    if forced:
        return forced, True
    last = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.language.isnot(None), Message.role == "user")
        .order_by(Message.created_at.desc())
        .first()
    )
    return detect_language(text) or (last.language if last else "en"), False


def _language_instruction(lang_code: str, forced: bool) -> str:
    lang_name = display_name_for(lang_code)
    if forced:
        return (
            f"IMPORTANT: regardless of what language this message is written in, "
            f"you must reply entirely in {lang_name}. Do not use English or any other language."
        )
    return f"The user is writing in {lang_name}. Reply fluently in {lang_name}, matching their language."


def _line(event: dict) -> bytes:
    return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")


def _finalise(message_id: str, conversation_id: str, content: str, status: str, error_code: str | None, model: str | None):
    """Runs after the request's DB session is gone, so it opens its own."""
    with session_scope() as db:
        message = db.get(Message, message_id)
        if message is None:  # conversation deleted mid-stream
            return
        message.content = content
        message.status = status
        message.error_code = error_code
        message.model = model
        conversation = db.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = now()


def _stream_assistant_reply(db: Session, conversation: Conversation, assistant: Message, llm_messages: list[dict]):
    stop_event = streams.register(assistant.id)
    result = StreamResult()
    replies = stream_reply(llm_messages, result, should_stop=stop_event.is_set)

    # Pull the first token before committing to a 200 streaming response, so provider
    # failures (timeouts, bad key, all fallbacks down) become a proper error response.
    try:
        first = next(replies)
    except StopIteration:
        first = None
    except LLMError as exc:
        streams.unregister(assistant.id)
        assistant.status, assistant.error_code = "failed", exc.code
        db.commit()
        log.warning("llm request failed before streaming", extra={"error_code": exc.code})
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "message_id": assistant.id}}, status_code=502
        )
    if first is None:
        streams.unregister(assistant.id)
        assistant.status, assistant.error_code = "failed", "EMPTY_REPLY"
        db.commit()
        return JSONResponse(
            {"error": {"code": "EMPTY_REPLY", "message": "The model returned an empty reply.", "message_id": assistant.id}},
            status_code=502,
        )

    assistant.status, assistant.model = "streaming", result.model
    db.commit()
    message_id, conversation_id = assistant.id, conversation.id

    def body():
        parts = [first]
        status, error_code = "completed", None
        try:
            yield _line({"type": "start", "message_id": message_id, "model": result.model})
            yield _line({"type": "delta", "text": first})
            for chunk in replies:
                parts.append(chunk)
                yield _line({"type": "delta", "text": chunk})
            if stop_event.is_set():
                status = "cancelled"
            yield _line({"type": "done", "status": status, "message_id": message_id})
        except LLMError as exc:
            status, error_code = "failed", exc.code
            yield _line({"type": "error", "code": exc.code, "message": exc.message, "message_id": message_id})
        except GeneratorExit:  # client disconnected / aborted the fetch
            status = "cancelled"
            raise
        finally:
            replies.close()
            streams.unregister(message_id)
            text = "".join(parts).strip()
            _finalise(message_id, conversation_id, text, status, error_code, result.model)
            log.info("reply %s", status, extra={"model": result.model, "error_code": error_code})

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"X-Assistant-Message-Id": message_id, "Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _prepare_turn(
    db: Session,
    user: User,
    conversation: Conversation,
    companion: Companion,
    user_message: Message,
    emotion: EmotionResult | None,
    lang_code: str,
    forced: bool,
):
    emotion_context = None
    if emotion is not None:
        strategy = strategy_for(emotion)
        user_message.response_strategy = strategy.name
        emotion_context = build_emotion_context(emotion, strategy, get_recent_emotions(db, user.id))

    assistant = Message(conversation_id=conversation.id, role="assistant", content="", status="pending", language=lang_code)
    db.add(assistant)
    db.flush()

    built = build_context(
        db,
        conversation,
        persona_prompt=companion.persona_prompt,
        emotion_context=emotion_context,
        language_instruction=_language_instruction(lang_code, forced),
        memory_enabled=user.memory_enabled,
        query_text=user_message.content,
    )
    maybe_enqueue_summary(db, conversation, built.unsummarized_count)
    db.commit()
    return _stream_assistant_reply(db, conversation, assistant, built.messages)


@router.post("/api/chat")
def api_chat(
    payload: ChatRequest,
    user: User = Depends(require_user_api),
    _limit: None = Depends(rate_limit("chat")),
    db: Session = Depends(get_db),
):
    conversation = get_conversation_for_user(db, user, payload.conversation_id)
    companion = get_companion_for_user(db, user, conversation.companion_id)
    message = payload.message
    lang_code, forced = _language_for(db, conversation, message, payload.preferred_language)

    user_message = Message(conversation_id=conversation.id, role="user", content=message, language=lang_code)
    db.add(user_message)
    if not conversation.title:  # auto-title new conversations from the first message
        conversation.title = message[:60] + ("..." if len(message) > 60 else "")

    emotion = None
    if user.emotion_tracking_enabled:
        emotion = detect_emotion(message)
        user_message.emotion, user_message.emotion_confidence = emotion.emotion, emotion.confidence
        record_emotion(db, user.id, emotion)
    db.flush()

    if user.memory_enabled and worth_extracting(message):
        enqueue(
            db,
            "extract_memories",
            {"message_id": user_message.id},
            user_id=user.id,
            dedupe_key=f"memory:{user_message.id}",
            max_attempts=2,
        )
    return _prepare_turn(db, user, conversation, companion, user_message, emotion, lang_code, forced)


@router.post("/api/chat/regenerate")
def api_regenerate(
    payload: RegenerateRequest,
    user: User = Depends(require_user_api),
    _limit: None = Depends(rate_limit("chat")),
    db: Session = Depends(get_db),
):
    """Retry a failed reply or regenerate the latest one: drops the conversation's last
    assistant message (if it is the last message) and answers the last user message again."""
    conversation = get_conversation_for_user(db, user, payload.conversation_id)
    companion = get_companion_for_user(db, user, conversation.companion_id)

    last = (
        db.query(Message).filter(Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).first()
    )
    if last is not None and last.role == "assistant":
        if last.status in ("pending", "streaming"):
            raise Conflict("A reply is still being generated.", code="REPLY_IN_PROGRESS")
        audio_key = last.voice_message.audio_path if last.voice_message else None
        db.delete(last)
        db.flush()
        storage.delete(audio_key)
        last = (
            db.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .first()
        )
    if last is None or last.role != "user":
        raise AppError("There is no message to reply to.", code="NOTHING_TO_REGENERATE", status_code=409)

    lang_code, forced = _language_for(db, conversation, last.content, payload.preferred_language)
    emotion = None
    if user.emotion_tracking_enabled and last.emotion:
        emotion = EmotionResult(last.emotion, last.emotion_confidence or 0.5, "stored")
    return _prepare_turn(db, user, conversation, companion, last, emotion, lang_code, forced)


@router.post("/api/messages/{message_id}/cancel")
def cancel_reply(message_id: str, user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    message = get_message_for_user(db, user, message_id)
    stopped = streams.request_stop(message.id)
    if not stopped and message.status in ("pending", "streaming"):
        # not streaming in this process (restart or another worker): don't leave it stuck
        message.status = "cancelled"
        db.commit()
    return {"ok": True, "status": "cancelling" if stopped else message.status}
