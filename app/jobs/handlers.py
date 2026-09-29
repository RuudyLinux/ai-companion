"""Job kind -> handler. Handlers take (db, job), return a JSON-able result, raise JobError."""

import logging
import time
from datetime import timedelta
from pathlib import Path

from conversation.summary import summarize_conversation
from core.config import settings
from memory.extraction import extract_memories
from models import Message, now
from privacy.service import run_retention
from voice.service import render_message_audio, render_voice_preview

log = logging.getLogger("app.worker")

TMP_FILE_TTL_SECONDS = 24 * 3600


HANDLERS = {
    "tts_message": render_message_audio,
    "tts_preview": render_voice_preview,
    "summarize_conversation": summarize_conversation,
    "extract_memories": extract_memories,
}


def _clean_tmp_dir() -> None:
    tmp_dir: Path = settings.data_dir / "tmp"
    if not tmp_dir.exists():
        return
    cutoff = time.time() - TMP_FILE_TTL_SECONDS
    for path in tmp_dir.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def fail_interrupted_replies(db) -> int:
    """Replies left pending/streaming by a crash or restart would otherwise look busy forever."""
    cutoff = now() - timedelta(minutes=10)
    count = (
        db.query(Message)
        .filter(Message.status.in_(("pending", "streaming")), Message.updated_at < cutoff)
        .update({Message.status: "failed", Message.error_code: "INTERRUPTED"}, synchronize_session=False)
    )
    db.commit()
    return count


def run_periodic_maintenance(db) -> None:
    fail_interrupted_replies(db)
    stats = run_retention(db)
    _clean_tmp_dir()
    log.info("maintenance done: %s", stats)
