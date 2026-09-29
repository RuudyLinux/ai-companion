"""
Single source of configuration. Everything is read from environment variables (a local
.env file is loaded for development). Import `settings` instead of calling os.environ
directly anywhere else in the app.
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent

load_dotenv(APP_DIR / ".env")


class ConfigError(RuntimeError):
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value is not None else default


def _float(name: str, default: float) -> float:
    value = _env(name)
    return float(value) if value is not None else default


def _list(name: str, default: str = "") -> list[str]:
    value = _env(name, default) or ""
    return [item.strip() for item in value.split(",") if item.strip()]


def _path(name: str, default: Path) -> Path:
    value = _env(name)
    path = Path(value) if value else default
    return path if path.is_absolute() else (APP_DIR / path).resolve()


VOICE_ENGINE_ALIASES = {
    # legacy VOICE_ENGINE_MODE values -> engine names
    "development": "xtts",
    "offline_production": "f5tts",
    "cloud_production": "inworld",
}
VALID_VOICE_ENGINES = {"xtts", "f5tts", "inworld"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    debug: bool
    log_level: str

    database_url: str
    auto_migrate: bool

    jwt_secret: str
    session_ttl_seconds: int
    cookie_secure: bool
    trusted_hosts: list[str]

    openrouter_api_key: str | None
    openrouter_base_url: str
    openrouter_model: str
    openrouter_fallback_models: list[str]
    llm_timeout_seconds: float
    llm_max_retries: int
    llm_max_output_tokens: int
    context_max_tokens: int
    context_recent_messages: int
    summary_trigger_messages: int

    voice_engine: str
    inworld_api_key: str | None
    stt_model: str
    stt_device: str
    stt_compute_type: str
    stt_timeout_seconds: int
    stt_max_concurrency: int

    max_upload_mb: int
    max_audio_seconds: int
    min_clone_audio_seconds: int
    max_message_chars: int

    data_dir: Path
    worker_mode: str  # embedded | external | off
    worker_poll_seconds: float
    job_timeout_seconds: int

    redis_url: str | None
    rate_limits: dict[str, str] = field(default_factory=dict)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def voice_audio_dir(self) -> Path:
        return self.data_dir / "voice_audio"

    @property
    def voice_refs_dir(self) -> Path:
        return self.data_dir / "voice_refs"

    @property
    def voice_previews_dir(self) -> Path:
        return self.data_dir / "voice_previews"


RATE_LIMIT_DEFAULTS = {
    # "<count>/<period>" where period is second|minute|hour|day
    "login": "10/minute",
    "signup": "5/hour",
    "chat": "30/minute",
    "stt": "20/minute",
    "tts": "30/minute",
    "voice_clone": "5/hour",
    "export": "5/hour",
}


def load_settings() -> Settings:
    app_env = (_env("APP_ENV", "development") or "development").lower()
    is_production = app_env == "production"

    jwt_secret = _env("JWT_SECRET")
    if not jwt_secret:
        if is_production:
            raise ConfigError("JWT_SECRET must be set in production")
        # dev/test convenience only: sessions won't survive restarts, which is fine locally
        jwt_secret = os.urandom(32).hex()
    if is_production and len(jwt_secret) < 32:
        raise ConfigError("JWT_SECRET must be at least 32 characters in production")

    raw_engine = (_env("VOICE_ENGINE") or _env("VOICE_ENGINE_MODE") or "xtts").lower()
    voice_engine = VOICE_ENGINE_ALIASES.get(raw_engine, raw_engine)
    if voice_engine not in VALID_VOICE_ENGINES:
        raise ConfigError(f"VOICE_ENGINE must be one of {sorted(VALID_VOICE_ENGINES)}, got {raw_engine!r}")

    worker_mode = (_env("WORKER_MODE", "embedded") or "embedded").lower()
    if worker_mode not in ("embedded", "external", "off"):
        raise ConfigError("WORKER_MODE must be embedded, external or off")

    data_dir = _path("DATA_DIR", APP_DIR / "data")
    database_url = _env("DATABASE_URL", f"sqlite:///{(data_dir / 'app.db').as_posix()}")
    # relative sqlite paths are resolved against app/ so the app works from any cwd
    if database_url.startswith("sqlite:///./"):
        database_url = f"sqlite:///{(APP_DIR / database_url[len('sqlite:///./'):]).as_posix()}"

    rate_limits = {
        name: _env(f"RATE_LIMIT_{name.upper()}", default) for name, default in RATE_LIMIT_DEFAULTS.items()
    }

    return Settings(
        app_env=app_env,
        debug=_bool("DEBUG", False),
        log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
        database_url=database_url,
        auto_migrate=_bool("AUTO_MIGRATE", not is_production),
        jwt_secret=jwt_secret,
        session_ttl_seconds=_int("SESSION_TTL", 60 * 60 * 24 * 7),
        cookie_secure=_bool("COOKIE_SECURE", is_production),
        trusted_hosts=_list("TRUSTED_HOSTS"),
        openrouter_api_key=_env("OPENROUTER_API_KEY"),
        openrouter_base_url=_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_model=_env("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        openrouter_fallback_models=_list("OPENROUTER_FALLBACK_MODELS"),
        llm_timeout_seconds=_float("LLM_TIMEOUT_SECONDS", 60.0),
        llm_max_retries=_int("LLM_MAX_RETRIES", 2),
        llm_max_output_tokens=_int("LLM_MAX_OUTPUT_TOKENS", 800),
        context_max_tokens=_int("CONTEXT_MAX_TOKENS", 6000),
        context_recent_messages=_int("CONTEXT_RECENT_MESSAGES", 20),
        summary_trigger_messages=_int("SUMMARY_TRIGGER_MESSAGES", 30),
        voice_engine=voice_engine,
        inworld_api_key=_env("INWORLD_API_KEY"),
        stt_model=_env("STT_MODEL", "base"),
        stt_device=_env("STT_DEVICE", "cpu"),
        stt_compute_type=_env("STT_COMPUTE_TYPE", "int8"),
        stt_timeout_seconds=_int("STT_TIMEOUT_SECONDS", 120),
        stt_max_concurrency=_int("STT_MAX_CONCURRENCY", 2),
        max_upload_mb=_int("MAX_UPLOAD_MB", 10),
        max_audio_seconds=_int("MAX_AUDIO_SECONDS", 120),
        min_clone_audio_seconds=_int("MIN_CLONE_AUDIO_SECONDS", 3),
        max_message_chars=_int("MAX_MESSAGE_CHARS", 4000),
        data_dir=data_dir,
        worker_mode=worker_mode,
        worker_poll_seconds=_float("WORKER_POLL_SECONDS", 1.0),
        job_timeout_seconds=_int("JOB_TIMEOUT_SECONDS", 600),
        redis_url=_env("REDIS_URL"),
        rate_limits=rate_limits,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


settings = get_settings()
