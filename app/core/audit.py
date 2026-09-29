import logging

from fastapi import Request
from sqlalchemy.orm import Session

from models import AuditLog, User

log = logging.getLogger("app.audit")


def record(
    db: Session,
    *,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: str | None,
    before: dict | None = None,
    after: dict | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Adds an audit row to the caller's transaction; it commits (or rolls back) with the change it describes."""
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
        request_id=getattr(request.state, "request_id", None) if request else None,
    )
    db.add(entry)
    log.info("audit %s %s:%s", action, target_type, target_id)
    return entry
