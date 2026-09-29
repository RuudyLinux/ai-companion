"""
Rolling conversation summaries, produced in the background worker.

When a conversation has more unsummarized messages than SUMMARY_TRIGGER_MESSAGES, the
oldest ones beyond the recent window are folded into `conversations.summary` together
with the previous summary. Messages are never deleted, and a failed summary leaves the
previous one untouched, so this can only ever reduce what's sent to the model.
"""

import logging

from sqlalchemy.orm import Session

from conversation.context import usable_history
from core.config import settings
from jobs.queue import JobError, enqueue
from llm.openrouter import LLMError, complete
from models import Conversation, Job, Message

log = logging.getLogger("app.summary")

MAX_MESSAGES_PER_PASS = 60
MAX_SUMMARY_CHARS = 2500

SUMMARY_PROMPT = """You maintain a running summary of a conversation between a user and their AI companion.
Update the summary with the new messages. Keep: facts the user shared, their feelings and what's going on in
their life, commitments or plans, open questions, and the tone of the relationship. Drop small talk.
Write in third person ("The user ..."), at most 200 words, plain text, no headings."""


def maybe_enqueue_summary(db: Session, conversation: Conversation, unsummarized_count: int) -> None:
    if unsummarized_count > settings.summary_trigger_messages:
        enqueue(
            db,
            "summarize_conversation",
            {"conversation_id": conversation.id},
            user_id=conversation.user_id,
            dedupe_key=f"summary:{conversation.id}",
            max_attempts=2,
        )


def summarize_conversation(db: Session, job: Job) -> dict:
    conversation = db.get(Conversation, (job.payload or {}).get("conversation_id"))
    if conversation is None:
        return {"summarized": 0}

    unsummarized = usable_history(db, conversation).order_by(Message.created_at.asc()).all()
    to_fold = unsummarized[: max(0, len(unsummarized) - settings.context_recent_messages)][:MAX_MESSAGES_PER_PASS]
    if not to_fold:
        return {"summarized": 0}

    transcript = "\n".join(f"{m.role.upper()}: {m.content[:2000]}" for m in to_fold)
    previous = conversation.summary or "(no summary yet)"
    try:
        summary, _model = complete(
            [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": f"Current summary:\n{previous}\n\nNew messages:\n{transcript}"},
            ],
            max_tokens=400,
        )
    except LLMError as exc:
        raise JobError(exc.code, "Summarizing the conversation failed.", retryable=exc.retryable) from exc
    if not summary:
        raise JobError("EMPTY_SUMMARY", "The model returned an empty summary.", retryable=True)

    conversation.summary = summary[:MAX_SUMMARY_CHARS]
    conversation.summarized_until = to_fold[-1].created_at
    db.commit()
    return {"summarized": len(to_fold)}
