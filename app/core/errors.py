"""
Centralised error handling. Every API error leaves the app as

    {"error": {"code": "VOICE_NOT_FOUND", "message": "The requested voice was not found."}}

Unexpected exceptions are logged with the request id and returned as a generic
INTERNAL_ERROR, never with a stack trace, file path or provider detail.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"
    message = "The request could not be processed."

    def __init__(self, message: str | None = None, *, code: str | None = None, status_code: int | None = None):
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        super().__init__(self.message)


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "Not found."


class Unauthorized(AppError):
    status_code = 401
    code = "NOT_AUTHENTICATED"
    message = "You need to sign in."


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"
    message = "You are not allowed to do that."


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"
    message = "That conflicts with the current state."


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "The request is invalid."


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many requests. Please slow down."

    def __init__(self, retry_after: int, message: str | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PayloadTooLarge(AppError):
    status_code = 413
    code = "PAYLOAD_TOO_LARGE"
    message = "The upload is too large."


class ServiceUnavailable(AppError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"
    message = "The service is temporarily unavailable."


_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def error_body(code: str, message: str, request: Request | None = None, details=None) -> dict:
    body = {"code": code, "message": message}
    if details:
        body["details"] = details
    request_id = getattr(request.state, "request_id", None) if request is not None else None
    if request_id:
        body["request_id"] = request_id
    return {"error": body}


def _wants_html(request: Request) -> bool:
    """Browser page navigations get pages/redirects; fetch()/API callers get JSON."""
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/media/") or path.startswith("/health"):
        return False
    return "text/html" in request.headers.get("accept", "")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        request.state.error_code = exc.code
        if exc.status_code == 401 and _wants_html(request):
            return RedirectResponse("/login", status_code=303)
        headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimited) else None
        return JSONResponse(error_body(exc.code, exc.message, request), status_code=exc.status_code, headers=headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        # require_user() uses a 303 + Location to bounce page requests to /login
        if exc.status_code in (302, 303, 307) and exc.headers and "Location" in exc.headers:
            return RedirectResponse(exc.headers["Location"], status_code=exc.status_code)
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        request.state.error_code = code
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(error_body(code, message, request), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        request.state.error_code = "VALIDATION_ERROR"
        details = [
            {"field": ".".join(str(p) for p in err.get("loc", ())[1:]) or None, "message": err.get("msg")}
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body("VALIDATION_ERROR", "The request is invalid.", request, details), status_code=422
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        request.state.error_code = "INTERNAL_ERROR"
        log.exception("unhandled error", extra={"error_code": "INTERNAL_ERROR"})
        return JSONResponse(
            error_body("INTERNAL_ERROR", "Something went wrong on our side.", request), status_code=500
        )
