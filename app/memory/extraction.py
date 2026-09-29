"""
Long-term memory extraction.

Strategy (deliberately conservative — most messages produce no memory):
1. Cheap pre-filter in the request path (`worth_extracting`): only first-person
   self-disclosure ("I am", "my sister", "I love", "remember that ...") queues a job.
2. In the background worker, an LLM turns the message into zero or more typed
   candidate memories as strict JSON.
3. Candidates are validated (type, length, confidence), screened for secrets, and
   de-duplicated against what's already stored (similar memories are merged, not
   duplicated). Per-user memory count is capped.
"""

import json
import logging
import re
from datetime import timedelta

from sqlalchemy.orm import Session

from jobs.queue import JobError
from llm.openrouter import LLMError, complete
from memory.text import similarity
from models import MEMORY_TYPES, Conversation, Job, Memory, Message, User, now

log = logging.getLogger("app.memory")

MIN_CONFIDENCE = 0.6
MAX_CONTENT_CHARS = 300
MAX_MEMORIES_PER_USER = 500
MERGE_SIMILARITY = 0.6
EXTRACTABLE_TYPES = [t for t in MEMORY_TYPES if t != "conversation_summary"]
COMPANION_SCOPED_TYPES = {"relationship"}  # everything else is about the user, shared across companions

_SELF_DISCLOSURE = re.compile(
    r"\b(i am|i'm|im|i was|i have|i've|i had|i live|i work|i study|i like|i love|i hate|i prefer|"
    r"i enjoy|i want|i need|i feel|i've been|my name|call me|my \w+|we are|we're|remember|"
    r"don't forget|birthday|anniversary|allergic)\b",
    re.IGNORECASE,
)

# never store credentials or payment data, even if the user shares them
_SENSITIVE = re.compile(
    r"(password|passcode|\bpin\b|api[ _-]?key|secret|token|cvv|\b(?:\d[ -]*?){13,19}\b|\b\d{3}-\d{2}-\d{4}\b)",
    re.IGNORECASE,
)

EXTRACTION_PROMPT = """You extract durable long-term memories about a user from one chat message they wrote.

Return ONLY a JSON array (no prose). Each item:
{"type": one of %(types)s,
 "content": short third-person statement about the user, e.g. "User's sister is named Priya",
 "importance": 0.0-1.0 (how useful for future conversations),
 "confidence": 0.0-1.0 (how sure this is literally true, not a joke or hypothetical),
 "ttl_days": null for lasting facts, or a number of days for temporary things (e.g. "exam next week" -> 14)}

Rules:
- Only facts the user states about themselves, their life, people close to them, likes/dislikes, goals, or upcoming events.
- Skip small talk, questions, hypotheticals, opinions about the assistant, and anything already obvious from context.
- Never include passwords, financial details, government IDs or other secrets.
- If nothing is worth remembering, return [].
"""


def worth_extracting(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) >= 12 and bool(_SELF_DISCLOSURE.search(stripped))


def _parse_candidates(raw: str) -> list[dict]:
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _clean(candidate: dict) -> dict | None:
    memory_type = candidate.get("type")
    content = str(candidate.get("content", "")).strip()
    try:
        confidence = float(candidate.get("confidence", 0))
        importance = float(candidate.get("importance", 0.5))
    except (TypeError, ValueError):
        return None
    if memory_type not in EXTRACTABLE_TYPES or not content or len(content) > MAX_CONTENT_CHARS:
        return None
    if confidence < MIN_CONFIDENCE or _SENSITIVE.search(content):
        return None
    ttl = candidate.get("ttl_days")
    ttl_days = int(ttl) if isinstance(ttl, int | float) and 0 < ttl <= 3650 else None
    return {
        "type": memory_type,
        "content": content,
        "confidence": min(1.0, max(0.0, confidence)),
        "importance": min(1.0, max(0.0, importance)),
        "ttl_days": ttl_days,
    }


def upsert_memory(db: Session, user_id: str, companion_id: str | None, data: dict, source_message_id: str | None):
    """Merges into a similar existing memory of the same type, or inserts a new one."""
    existing = (
        db.query(Memory)
        .filter(Memory.user_id == user_id, Memory.type == data["type"])
        .order_by(Memory.updated_at.desc())
        .limit(200)
        .all()
    )
    best = max(existing, key=lambda m: similarity(m.content, data["content"]), default=None)
    expires_at = now() + timedelta(days=data["ttl_days"]) if data.get("ttl_days") else None
    if best is not None and similarity(best.content, data["content"]) >= MERGE_SIMILARITY:
        best.content = data["content"]  # newer phrasing wins (facts change: "moved to Pune")
        best.importance = max(best.importance, data["importance"])
        best.confidence = max(best.confidence, data["confidence"])
        best.expires_at = expires_at
        best.source_message_id = source_message_id or best.source_message_id
        return best
    memory = Memory(
        user_id=user_id,
        companion_id=companion_id,
        type=data["type"],
        content=data["content"],
        importance=data["importance"],
        confidence=data["confidence"],
        source_message_id=source_message_id,
        expires_at=expires_at,
    )
    db.add(memory)
    return memory


def _enforce_cap(db: Session, user_id: str) -> None:
    count = db.query(Memory).filter(Memory.user_id == user_id).count()
    overflow = count - MAX_MEMORIES_PER_USER
    if overflow > 0:
        victims = (
            db.query(Memory)
            .filter(Memory.user_id == user_id)
            .order_by(Memory.importance.asc(), Memory.updated_at.asc())
            .limit(overflow)
            .all()
        )
        for victim in victims:
            db.delete(victim)


def extract_memories(db: Session, job: Job) -> dict:
    message = db.get(Message, (job.payload or {}).get("message_id"))
    user = db.get(User, job.user_id)
    if message is None or user is None or message.role != "user":
        return {"stored": 0}
    conversation = db.get(Conversation, message.conversation_id)
    if conversation is None or conversation.user_id != user.id:
        return {"stored": 0}
    if not user.memory_enabled:  # setting may have changed since the job was queued
        return {"stored": 0}

    prompt = EXTRACTION_PROMPT % {"types": ", ".join(EXTRACTABLE_TYPES)}
    try:
        raw, _model = complete(
            [{"role": "system", "content": prompt}, {"role": "user", "content": message.content}],
            max_tokens=400,
            temperature=0.0,
        )
    except LLMError as exc:
        raise JobError(exc.code, "Memory extraction failed.", retryable=exc.retryable) from exc

    stored = 0
    for candidate in _parse_candidates(raw):
        data = _clean(candidate)
        if data is None:
            continue
        companion_id = conversation.companion_id if data["type"] in COMPANION_SCOPED_TYPES else None
        upsert_memory(db, user.id, companion_id, data, message.id)
        stored += 1
    _enforce_cap(db, user.id)
    db.commit()
    return {"stored": stored}
