"""
Test harness. Environment is configured before any app module is imported, so the app
runs against a throwaway SQLite database and data dir, with background workers off
(tests run jobs explicitly) and no real LLM / TTS / STT calls.
"""

import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="companion-tests-"))
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "DATA_DIR": str(_TMP / "data"),
        "JWT_SECRET": "test-secret-" + "x" * 40,
        "WORKER_MODE": "off",
        "AUTO_MIGRATE": "false",
        "OPENROUTER_API_KEY": "test-key",
        "VOICE_ENGINE": "xtts",
        "LLM_MAX_RETRIES": "0",
        "LOG_LEVEL": "WARNING",
        "MAX_UPLOAD_MB": "2",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import soundfile as sf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from auth import hash_password  # noqa: E402
from core import rate_limit, storage  # noqa: E402
from core.migrations import upgrade_database  # noqa: E402
from database import Base, SessionLocal, engine  # noqa: E402
from main import app  # noqa: E402
from models import Companion, Conversation, Message, User, Voice  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session", autouse=True)
def _database():
    upgrade_database()  # the real migrations, so every test also exercises them
    storage.ensure_dirs()
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {table.name}"))
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.commit()
    rate_limit.backend.reset()
    for sub in ("voice_audio", "voice_refs", "voice_previews", "tmp"):
        for path in (storage.settings.data_dir / sub).glob("*"):
            path.unlink(missing_ok=True)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


class Client(TestClient):
    """TestClient that behaves like the browser app: picks up the CSRF cookie and sends
    it back as X-CSRF-Token on every unsafe request."""

    def request(self, method, url, *args, **kwargs):
        if method.upper() not in ("GET", "HEAD", "OPTIONS") and kwargs.pop("csrf", True):
            if "csrf_token" not in self.cookies:
                super().request("GET", "/health/live")
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("X-CSRF-Token", self.cookies.get("csrf_token"))
            kwargs["headers"] = headers
        return super().request(method, url, *args, **kwargs)


def make_user(db, email: str, role: str = "user") -> User:
    user = User(email=email, hashed_password=hash_password(PASSWORD), role=role)
    db.add(user)
    db.commit()
    return user


def login(client: Client, email: str) -> None:
    res = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/companions", res.text


@pytest.fixture
def client():
    with Client(app) as c:
        yield c


@pytest.fixture
def make_client():
    clients = []

    def factory(email: str | None = None, role: str = "user"):
        c = Client(app)
        c.__enter__()
        clients.append(c)
        if email:
            with SessionLocal() as session:
                make_user(session, email, role)
            login(c, email)
        return c

    yield factory
    for c in clients:
        c.__exit__(None, None, None)


def user_by_email(db, email: str) -> User:
    return db.query(User).filter(User.email == email).one()


def make_companion(db, owner: User, name="Nova", public=False) -> Companion:
    companion = Companion(owner_id=owner.id, name=name, persona_prompt=f"You are {name}.", is_public=public)
    db.add(companion)
    db.commit()
    return companion


def make_conversation(db, user: User, companion: Companion, messages: list[tuple[str, str]] = ()) -> Conversation:
    conversation = Conversation(user_id=user.id, companion_id=companion.id)
    db.add(conversation)
    db.flush()
    for role, content in messages:
        db.add(Message(conversation_id=conversation.id, role=role, content=content, status="completed"))
        db.flush()
    db.commit()
    return conversation


def make_voice(db, owner: User | None = None, name="Ana") -> Voice:
    if owner is None:
        voice = Voice(name=name, category="female", kind="builtin", provider="xtts", provider_voice_id=name)
    else:
        voice = Voice(name=name, category="cloned", kind="cloned", provider="xtts", owner_id=owner.id)
    db.add(voice)
    db.commit()
    return voice


def wav_bytes(seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    t = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
    buffer = io.BytesIO()
    sf.write(buffer, (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sample_rate, format="WAV")
    return buffer.getvalue()


class FakeEngine:
    """Stands in for XTTS: writes a short sine wave instead of running a GPU model."""

    name = "xtts"
    clone_needs_raw_file = True

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = []

    def synthesize(self, text, out_path, language="en", speaker_wav=None, speaker_name=None):
        self.calls.append({"text": text, "speaker_wav": speaker_wav, "speaker_name": speaker_name})
        if self.fail:
            raise RuntimeError("CUDA out of memory at C:\\secret\\path")
        Path(out_path).write_bytes(wav_bytes(0.5, 22050))

    def register_clone(self, *args):
        return None

    def builtin_speakers(self):
        return []

    def supports_language(self, code):
        return code in ("en", "es", "hi")


@pytest.fixture
def fake_engine(monkeypatch):
    engine_instance = FakeEngine()
    import routers.speech
    import voice.service

    monkeypatch.setattr(voice.service, "get_engine", lambda: engine_instance)
    monkeypatch.setattr(routers.speech, "get_engine", lambda: engine_instance)
    return engine_instance


def run_jobs(queue_names=("tts", "background")) -> int:
    """Runs every queued job synchronously, like the worker would."""
    from jobs.queue import claim_next
    from jobs.worker import run_one

    ran = 0
    with SessionLocal() as session:
        while (job := claim_next(session, list(queue_names), "test-worker")) is not None:
            run_one(session, job)
            ran += 1
    return ran


class FakeChunk:
    def __init__(self, text=None, finish_reason=None):
        delta = type("Delta", (), {"content": text})()
        self.choices = [type("Choice", (), {"delta": delta, "finish_reason": finish_reason})()]


@pytest.fixture
def fake_llm(monkeypatch):
    """Replaces the OpenRouter client. Set `.replies` (list of chunks) or `.error`."""
    import llm.openrouter as llm

    class FakeStream:
        def __init__(self, chunks):
            self._chunks = chunks

        def __iter__(self):
            for item in self._chunks:
                if isinstance(item, Exception):
                    raise item
                yield FakeChunk(item)

        def close(self):
            pass

    class FakeCompletions:
        def __init__(self):
            self.replies = ["Hello ", "there!"]
            self.error = None
            self.completion_text = "[]"
            self.requests = []

        def create(self, **kwargs):
            self.requests.append(kwargs)
            if self.error:
                raise self.error
            if kwargs.get("stream"):
                return FakeStream(list(self.replies))
            message = type("Msg", (), {"content": self.completion_text})()
            return type("Resp", (), {"choices": [type("C", (), {"message": message})()]})()

    completions = FakeCompletions()
    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    monkeypatch.setattr(llm, "_client", lambda: fake_client)
    return completions
