import sys

# Some libraries (e.g. F5-TTS) print non-ASCII text (reference transcripts in Hindi/
# Urdu/etc.) straight to stdout — Windows' default console codepage (cp1252) crashes
# on that. Reconfiguring here, once, at process start, so no library's internal print()
# can ever take the server down.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import Depends, FastAPI, Request  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

from auth import get_current_user  # noqa: E402
from core import storage  # noqa: E402
from core.config import settings  # noqa: E402
from core.errors import install_error_handlers  # noqa: E402
from core.logging import RequestContextMiddleware, configure_logging  # noqa: E402
from core.security import (  # noqa: E402
    BodySizeLimitMiddleware,
    CSRFCookieMiddleware,
    SecurityHeadersMiddleware,
    csrf_protect,
)
from database import get_db  # noqa: E402
from routers import (  # noqa: E402
    admin,
    auth_routes,
    chat,
    companions,
    conversations,
    health,
    privacy,
    settings_routes,
    speech,
    voice_library,
    voice_messages,
)
from templating import templates  # noqa: E402

configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.ensure_dirs()
    if settings.auto_migrate:
        from core.migrations import upgrade_database

        upgrade_database()
    if settings.worker_mode == "embedded":
        from jobs.worker import start_embedded, stop_embedded

        start_embedded()
        yield
        stop_embedded()
    else:
        yield


app = FastAPI(
    title="AI Companion Platform",
    lifespan=lifespan,
    dependencies=[Depends(csrf_protect)],
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
    openapi_url="/openapi.json" if not settings.is_production else None,
)
install_error_handlers(app)

# the last one added is outermost: request id/logging wraps everything, including rejected bodies
app.add_middleware(CSRFCookieMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes + 256 * 1024)
if settings.trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(RequestContextMiddleware)

app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")

for module in (
    health,
    auth_routes,
    companions,
    chat,
    speech,
    settings_routes,
    privacy,
    admin,
    conversations,
    voice_messages,
    voice_library,
):
    app.include_router(module.router)


@app.get("/")
def landing(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/companions", status_code=303)
    return templates.TemplateResponse(request, "landing.html", {})
