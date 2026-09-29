import time
from functools import lru_cache

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.config import APP_DIR, settings
from database import engine
from emotion.classifier import model_available

router = APIRouter()

_started = time.time()


@lru_cache(maxsize=1)
def _expected_heads() -> frozenset[str]:
    config = Config(str(APP_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(APP_DIR / "migrations"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


@router.get("/health/live")
def live():
    """Process is up. No dependencies checked — for restart decisions only."""
    return {"status": "ok"}


def _readiness() -> tuple[bool, dict[str, str]]:
    checks: dict[str, str] = {}
    healthy = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            current = set(MigrationContext.configure(conn).get_current_heads())
        checks["database"] = "ok"
        checks["migrations"] = "ok" if current == _expected_heads() else "pending"
        healthy = checks["migrations"] == "ok"
    except Exception:
        checks["database"] = "unavailable"
        healthy = False
    checks["llm"] = "configured" if settings.openrouter_api_key else "not_configured"
    checks["emotion_model"] = "loaded" if model_available() else "keyword_fallback"
    return healthy, checks


@router.get("/health/ready")
def ready():
    """Can serve traffic: database reachable and schema migrated to the latest revision."""
    healthy, checks = _readiness()
    return JSONResponse({"status": "ok" if healthy else "unavailable", "checks": checks}, status_code=200 if healthy else 503)


@router.get("/health")
def health():
    healthy, checks = _readiness()
    return JSONResponse(
        {
            "status": "ok" if healthy else "unavailable",
            "checks": checks,
            "environment": settings.app_env,
            "voice_engine": settings.voice_engine,
            "worker_mode": settings.worker_mode,
            "uptime_seconds": int(time.time() - _started),
        },
        status_code=200 if healthy else 503,
    )
