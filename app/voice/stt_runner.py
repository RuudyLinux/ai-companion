"""
Runs Whisper transcription in a child process (scripts/transcribe_cli.py).

The process boundary is required, not a style choice: ctranslate2 (faster-whisper) and
torch (XTTS/F5-TTS) bundle clashing CUDA runtimes and crash when loaded in one process.
This wrapper adds what the bare subprocess call lacked: a concurrency cap, a timeout
that kills the child, return-code checks and typed errors.
"""

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path

from core.config import settings
from core.errors import AppError

log = logging.getLogger("app.stt")

TRANSCRIBE_CLI = Path(__file__).resolve().parent.parent / "scripts" / "transcribe_cli.py"

_slots = threading.BoundedSemaphore(max(1, settings.stt_max_concurrency))
QUEUE_WAIT_SECONDS = 30


class STTError(AppError):
    status_code = 502
    code = "STT_FAILED"
    message = "Speech recognition failed. Please try again."


class STTBusy(AppError):
    status_code = 503
    code = "STT_BUSY"
    message = "Speech recognition is busy. Please try again in a moment."


class STTTimeout(AppError):
    status_code = 504
    code = "STT_TIMEOUT"
    message = "Speech recognition took too long."


def run_transcription(audio_path: str) -> dict:
    """Returns {"text": str, "language": str | None}. Raises STTError/STTBusy/STTTimeout."""
    if not _slots.acquire(timeout=QUEUE_WAIT_SECONDS):
        raise STTBusy()
    try:
        try:
            completed = subprocess.run(
                [sys.executable, str(TRANSCRIBE_CLI), audio_path],
                capture_output=True,
                timeout=settings.stt_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:  # subprocess.run kills the child before raising
            raise STTTimeout() from exc
        except OSError as exc:
            log.error("could not start transcription process", extra={"error_code": "STT_SPAWN_FAILED"})
            raise STTError() from exc
    finally:
        _slots.release()

    if completed.returncode != 0:
        # stderr can hold library tracebacks; log a bounded tail, never return it to clients
        tail = completed.stderr.decode("utf-8", errors="replace")[-800:]
        log.error(
            "transcription process failed: rc=%s %s",
            completed.returncode,
            tail,
            extra={"error_code": "STT_FAILED"},
        )
        raise STTError()

    try:
        data = json.loads(completed.stdout.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError as exc:
        raise STTError() from exc
    return {"text": str(data.get("text", "")).strip(), "language": data.get("language")}
