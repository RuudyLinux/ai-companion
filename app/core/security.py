"""
Browser-request protections:

- CSRF: signed double-submit token. A `csrf_token` cookie is issued to every visitor;
  every unsafe request (POST/PUT/PATCH/DELETE) must echo it back, either as the
  `X-CSRF-Token` header (fetch) or a `csrf_token` form field (HTML forms). A
  cross-site attacker can make the browser *send* the cookie but can't *read* it, so
  they can't supply the matching value. The HMAC signature stops a sibling subdomain
  from planting a cookie value it chose.
- Request body size cap, enforced while the body streams in, before anything parses it.
- Baseline security headers.
"""

import hashlib
import hmac
import json
import secrets

from fastapi import Request

from core.config import settings
from core.errors import Forbidden, error_body

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "x-csrf-token"
CSRF_FORM_FIELD = "csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _sign(raw: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), f"csrf:{raw}".encode(), hashlib.sha256).hexdigest()[:32]


def new_csrf_token() -> str:
    raw = secrets.token_urlsafe(24)
    return f"{raw}.{_sign(raw)}"


def csrf_token_is_valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    raw, signature = token.rsplit(".", 1)
    return hmac.compare_digest(signature, _sign(raw))


class CSRFFailed(Forbidden):
    code = "CSRF_FAILED"
    message = "Your session form token is missing or expired. Reload the page and try again."


async def csrf_protect(request: Request) -> None:
    """Global dependency: validates the CSRF token on every unsafe request."""
    if request.method in SAFE_METHODS:
        return

    cookie_token = request.cookies.get(CSRF_COOKIE)
    submitted = request.headers.get(CSRF_HEADER)
    content_type = request.headers.get("content-type", "")
    # only urlencoded bodies are parsed here; multipart uploads must use the header so we
    # never spool an attacker's upload to disk just to look for a token
    if not submitted and content_type.startswith("application/x-www-form-urlencoded"):
        form = await request.form()  # Starlette caches this; route handlers reuse it
        value = form.get(CSRF_FORM_FIELD)
        submitted = value if isinstance(value, str) else None

    if not (csrf_token_is_valid(cookie_token) and submitted and hmac.compare_digest(cookie_token, submitted)):
        raise CSRFFailed()


class CSRFCookieMiddleware:
    """Makes sure every visitor has a CSRF cookie and exposes it to templates via request.state."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = None
        for key, value in scope.get("headers") or []:
            if key == b"cookie":
                for part in value.decode("latin-1").split(";"):
                    name, _, cookie_value = part.strip().partition("=")
                    if name == CSRF_COOKIE:
                        token = cookie_value
        issue_new = not csrf_token_is_valid(token)
        if issue_new:
            token = new_csrf_token()
        scope.setdefault("state", {})["csrf_token"] = token

        async def send_wrapper(message):
            if issue_new and message["type"] == "http.response.start":
                cookie = f"{CSRF_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000"
                if settings.cookie_secure:
                    cookie += "; Secure"
                message["headers"] = [*message.get("headers", []), (b"set-cookie", cookie.encode("latin-1"))]
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    """Rejects request bodies over the limit while they stream in (Content-Length or chunked)."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not response_started:
                await self._reject(send)

    async def _reject(self, send):
        body = json.dumps(
            error_body("PAYLOAD_TOO_LARGE", f"Uploads are limited to {settings.max_upload_mb} MB.")
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass


SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), geolocation=(), microphone=(self)"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(SECURITY_HEADERS)
                if settings.cookie_secure:
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
