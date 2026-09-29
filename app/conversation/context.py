"""
Builds the LLM prompt for a turn without sending the whole history:

    system  = companion persona
            + current emotional context and response strategy
            + relevant long-term memories
            + rolling summary of older conversation
            + language instruction
    then    = most recent messages that fit the token budget

Older messages stay in the database; they reach the model only through the summary
(conversation/summary.py) and extracted memories.
"""

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.config import settings
from memory.retrieval import format_memories, retrieve_memories
from models import Conversation, Message

CHARS_PER_TOKEN = 4  # rough, provider-agnostic estimate; errs on the safe side for English


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 4


def usable_history(db: Session, conversation: Conversation):
    """Messages the model may see: completed ones, and cancelled replies that got some text.
    Failed/pending/empty rows are never replayed as context."""
    query = db.query(Message).filter(
        Message.conversation_id == conversation.id,
        Message.content != "",
        or_(Message.status == "completed", Message.status == "cancelled"),
    )
    if conversation.summarized_until is not None:
        query = query.filter(Message.created_at > conversation.summarized_until)
    return query


@dataclass
class BuiltContext:
    messages: list[dict]
    unsummarized_count: int
    memory_count: int


def build_context(
    db: Session,
    conversation: Conversation,
    *,
    persona_prompt: str,
    emotion_context: str | None,
    language_instruction: str,
    memory_enabled: bool,
    query_text: str,
    exclude_message_ids: set[str] | None = None,
) -> BuiltContext:
    system_parts = [persona_prompt]
    if emotion_context:
        system_parts.append(emotion_context)

    memories = []
    if memory_enabled:
        memories = retrieve_memories(db, conversation.user_id, conversation.companion_id, query_text)
        if memories:
            system_parts.append(
                "What you remember about the user from earlier conversations (use naturally, don't recite):\n"
                + format_memories(memories)
            )
    if conversation.summary:
        system_parts.append(f"Summary of the earlier part of this conversation:\n{conversation.summary}")
    system_parts.append(language_instruction)
    system_prompt = "\n\n".join(system_parts)

    budget = settings.context_max_tokens - estimate_tokens(system_prompt) - settings.llm_max_output_tokens
    recent = (
        usable_history(db, conversation)
        .order_by(Message.created_at.desc())
        .limit(settings.context_recent_messages)
        .all()
    )
    exclude = exclude_message_ids or set()
    chosen: list[Message] = []
    for message in recent:  # newest first, so the budget keeps the latest turns
        if message.id in exclude:
            continue
        cost = estimate_tokens(message.content)
        if chosen and cost > budget:
            break
        budget -= cost
        chosen.append(message)
    chosen.reverse()

    history = [{"role": m.role, "content": m.content} for m in chosen]
    # a conversation must not start with an orphaned assistant turn after truncation
    while history and history[0]["role"] == "assistant" and len(history) > 1:
        history.pop(0)

    return BuiltContext(
        messages=[{"role": "system", "content": system_prompt}, *history],
        unsummarized_count=usable_history(db, conversation).count(),
        memory_count=len(memories),
    )
