"""
Memory retrieval for prompt building.

Scoring = lexical relevance to the current message + stored importance + recency, plus
the user's top profile facts always included. Relevance is word-overlap today; to move
to semantic memory on PostgreSQL, add a pgvector `embedding` column to `memories`,
fill it in memory/extraction.py, and replace `_relevance()` with a cosine-distance
ORDER BY — callers only depend on `retrieve_memories()`.
"""

from datetime import timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from memory.text import tokens
from models import Memory, as_utc, now

MAX_MEMORIES_IN_PROMPT = 8
MAX_MEMORY_CHARS_IN_PROMPT = 1500
ALWAYS_INCLUDE_PROFILE = 3
RECENCY_HALF_LIFE_DAYS = 30


def _relevance(query_tokens: set[str], memory: Memory) -> float:
    memory_tokens = tokens(memory.content)
    if not query_tokens or not memory_tokens:
        return 0.0
    return len(query_tokens & memory_tokens) / len(memory_tokens)


def _recency(memory: Memory) -> float:
    updated = as_utc(memory.updated_at) or now()
    age_days = max(0.0, (now() - updated).total_seconds() / 86400)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def active_memories(db: Session, user_id: str, companion_id: str | None):
    return db.query(Memory).filter(
        Memory.user_id == user_id,
        or_(Memory.expires_at.is_(None), Memory.expires_at > now()),
        or_(Memory.companion_id.is_(None), Memory.companion_id == companion_id),
    )


def retrieve_memories(db: Session, user_id: str, companion_id: str | None, query: str) -> list[Memory]:
    candidates = active_memories(db, user_id, companion_id).limit(1000).all()
    if not candidates:
        return []

    query_tokens = tokens(query)
    scored = sorted(
        candidates,
        key=lambda m: 0.55 * _relevance(query_tokens, m) + 0.3 * m.importance + 0.15 * _recency(m),
        reverse=True,
    )
    profile = sorted((m for m in candidates if m.type == "profile"), key=lambda m: m.importance, reverse=True)

    chosen: list[Memory] = []
    used_chars = 0
    for memory in [*profile[:ALWAYS_INCLUDE_PROFILE], *scored]:
        if memory in chosen:
            continue
        if len(chosen) >= MAX_MEMORIES_IN_PROMPT or used_chars + len(memory.content) > MAX_MEMORY_CHARS_IN_PROMPT:
            break
        chosen.append(memory)
        used_chars += len(memory.content)

    touched = now()
    for memory in chosen:
        last = as_utc(memory.last_used_at)
        if last is None or touched - last > timedelta(hours=1):
            memory.last_used_at = touched
    return chosen


def format_memories(memories: list[Memory]) -> str:
    return "\n".join(f"- ({m.type}) {m.content}" for m in memories)
