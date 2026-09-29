"""
Database-backed job queue. The `jobs` table is the queue, so there is no extra
infrastructure to run locally and it works the same on SQLite and PostgreSQL.

Claiming is a single conditional UPDATE (`... WHERE id = ? AND status = 'queued'`), so
two workers can never both win the same job.
"""

from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from models import Job, as_utc, now

QUEUES = ("tts", "background")
ACTIVE_STATUSES = ("queued", "processing")
FINAL_STATUSES = ("completed", "failed", "cancelled")


class JobError(Exception):
    """Raised by handlers. `retryable` failures are re-queued while attempts remain."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def enqueue(
    db: Session,
    kind: str,
    payload: dict,
    *,
    queue: str = "background",
    user_id: str | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = 1,
    delay_seconds: float = 0,
) -> Job:
    """Adds a job to the caller's transaction. With a dedupe_key, an identical job that is
    still queued/processing is returned instead of creating a duplicate."""
    if dedupe_key:
        existing = (
            db.query(Job)
            .filter(Job.dedupe_key == dedupe_key, Job.status.in_(ACTIVE_STATUSES))
            .order_by(Job.created_at.desc())
            .first()
        )
        if existing:
            return existing
    job = Job(
        kind=kind,
        queue=queue,
        payload=payload,
        user_id=user_id,
        dedupe_key=dedupe_key,
        max_attempts=max_attempts,
        run_after=now() + timedelta(seconds=delay_seconds),
    )
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session, queues: list[str], worker_id: str) -> Job | None:
    candidates = (
        db.query(Job.id)
        .filter(Job.queue.in_(queues), Job.status == "queued", Job.run_after <= now())
        .order_by(Job.created_at)
        .limit(10)
        .all()
    )
    for (job_id,) in candidates:
        claimed = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="processing", locked_by=worker_id, started_at=now(), attempts=Job.attempts + 1)
        ).rowcount
        db.commit()
        if claimed == 1:
            return db.get(Job, job_id)
    return None


def finish(db: Session, job: Job, result: dict) -> bool:
    """Marks a processing job completed. Returns False if it was cancelled meanwhile."""
    updated = db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == "processing")
        .values(status="completed", result=result, finished_at=now(), error_code=None, error_message=None)
    ).rowcount
    db.commit()
    return updated == 1


def fail(db: Session, job: Job, code: str, message: str, retryable: bool) -> None:
    retry = retryable and job.attempts < job.max_attempts
    values = (
        {"status": "queued", "run_after": now() + timedelta(seconds=5 * 2 ** job.attempts), "locked_by": None}
        if retry
        else {"status": "failed", "finished_at": now()}
    )
    db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == "processing")
        .values(error_code=code, error_message=message[:500], **values)
    )
    db.commit()


def cancel(db: Session, job: Job) -> bool:
    updated = db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status.in_(ACTIVE_STATUSES))
        .values(status="cancelled", finished_at=now())
    ).rowcount
    db.commit()
    return updated == 1


def requeue_stale(db: Session, timeout_seconds: int) -> int:
    """Jobs whose worker died mid-run: retry if attempts remain, otherwise fail."""
    cutoff = now() - timedelta(seconds=timeout_seconds)
    stale = db.query(Job).filter(Job.status == "processing", Job.started_at < cutoff).all()
    for job in stale:
        if job.attempts < job.max_attempts:
            job.status, job.locked_by = "queued", None
        else:
            job.status, job.finished_at = "failed", now()
            job.error_code, job.error_message = "JOB_TIMEOUT", "The job did not finish in time."
    db.commit()
    return len(stale)


def job_view(job: Job) -> dict:
    """Client-safe representation (no payload internals)."""
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "result": job.result if job.status == "completed" else None,
        "error": {"code": job.error_code, "message": job.error_message} if job.status == "failed" else None,
        "created_at": as_utc(job.created_at).isoformat() if job.created_at else None,
    }
