"""
Job worker. Two ways to run it:

- WORKER_MODE=embedded (development default): started as daemon threads inside the web
  process by main.py, so `uvicorn main:app` is all you need locally.
- WORKER_MODE=external (production): the web process only enqueues; run workers
  separately, e.g.

      python -m jobs.worker --queues tts            # GPU box, one process
      python -m jobs.worker --queues background     # summaries, memory, retention

The "tts" queue gets its own worker because model inference is GPU-bound and
single-flight; "background" work is light LLM calls and DB maintenance.
"""

import argparse
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings  # noqa: E402
from database import SessionLocal  # noqa: E402
from jobs import queue  # noqa: E402
from jobs.handlers import HANDLERS, run_periodic_maintenance  # noqa: E402
from models import Job  # noqa: E402

log = logging.getLogger("app.worker")

MAINTENANCE_INTERVAL_SECONDS = 15 * 60


def run_one(db, job: Job) -> None:
    handler = HANDLERS.get(job.kind)
    extra = {"job_id": job.id, "job_kind": job.kind, "attempt": job.attempts}
    started = time.perf_counter()
    if handler is None:
        queue.fail(db, job, "UNKNOWN_JOB_KIND", "Unknown job type.", retryable=False)
        log.error("unknown job kind", extra=extra)
        return
    try:
        result = handler(db, job)
    except queue.JobError as exc:
        db.rollback()
        queue.fail(db, job, exc.code, exc.message, exc.retryable)
        log.warning("job failed", extra={**extra, "error_code": exc.code})
        return
    except Exception:
        db.rollback()
        queue.fail(db, job, "JOB_CRASHED", "The job failed unexpectedly.", retryable=True)
        log.exception("job crashed", extra={**extra, "error_code": "JOB_CRASHED"})
        return
    if not queue.finish(db, job, result or {}):
        log.info("job finished after cancellation; status left as cancelled", extra=extra)
        return
    log.info("job completed", extra={**extra, "latency_ms": round((time.perf_counter() - started) * 1000, 1)})


def work(queues: list[str], stop: threading.Event, worker_id: str, run_maintenance: bool) -> None:
    last_maintenance = 0.0
    while not stop.is_set():
        db = SessionLocal()
        try:
            if run_maintenance and time.time() - last_maintenance > MAINTENANCE_INTERVAL_SECONDS:
                last_maintenance = time.time()
                queue.requeue_stale(db, settings.job_timeout_seconds)
                run_periodic_maintenance(db)
            job = queue.claim_next(db, queues, worker_id)
            if job is None:
                stop.wait(settings.worker_poll_seconds)
                continue
            run_one(db, job)
        except Exception:
            log.exception("worker loop error")
            stop.wait(settings.worker_poll_seconds * 5)
        finally:
            db.close()


_threads: list[threading.Thread] = []
_stop = threading.Event()


def start_embedded() -> None:
    """Starts one daemon thread per queue inside the web process."""
    if _threads:
        return
    _stop.clear()
    for index, name in enumerate(queue.QUEUES):
        worker_id = f"{socket.gethostname()}:{os.getpid()}:{name}"
        thread = threading.Thread(
            target=work, args=([name], _stop, worker_id, index == 0), name=f"worker-{name}", daemon=True
        )
        thread.start()
        _threads.append(thread)


def stop_embedded(timeout: float = 5.0) -> None:
    _stop.set()
    for thread in _threads:
        thread.join(timeout)
    _threads.clear()


def main() -> None:
    from core.logging import configure_logging

    parser = argparse.ArgumentParser(description="AI Companion background worker")
    parser.add_argument("--queues", default=",".join(queue.QUEUES), help="comma-separated: tts,background")
    parser.add_argument("--no-maintenance", action="store_true", help="skip retention/stale-job sweeps")
    args = parser.parse_args()
    configure_logging()

    queues = [q.strip() for q in args.queues.split(",") if q.strip()]
    unknown = set(queues) - set(queue.QUEUES)
    if unknown:
        parser.error(f"unknown queues: {sorted(unknown)}")

    stop = threading.Event()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    log.info("worker starting", extra={"route": ",".join(queues)})
    try:
        work(queues, stop, worker_id, run_maintenance=not args.no_maintenance)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
