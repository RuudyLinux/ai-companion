"""
Structured (JSON-lines) logging plus a request-context middleware that assigns every
request an id, echoes it as X-Request-ID, and logs one access line per request.

Never pass passwords, tokens, API keys, message content or audio to the logger.
"""

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timezone

from core.config import settings

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_EXTRA_FIELDS = (
    "route", "method", "status", "latency_ms", "model", "voice_engine", "error_code",
    "job_id", "job_kind", "attempt", "client_ip",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
        }
        for key in _EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps({k: v for k, v in entry.items() if v is not None}, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
    # uvicorn's own access log would duplicate ours (and without request ids)
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "numba", "matplotlib", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


access_log = logging.getLogger("app.access")


class RequestContextMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so streaming responses aren't buffered."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        rid_token = request_id_var.set(request_id)
        uid_token = user_id_var.set(None)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            state = scope.get("state", {})
            # set by auth in a threadpool thread, where contextvar writes don't propagate back
            user_id_var.set(state.get("user_id"))
            access_log.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "route": getattr(route, "path", None) or scope.get("path"),
                    "status": status_holder["status"],
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error_code": state.get("error_code"),
                    "client_ip": (scope.get("client") or (None,))[0],
                },
            )
            request_id_var.reset(rid_token)
            user_id_var.reset(uid_token)
