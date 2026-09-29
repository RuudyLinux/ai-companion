# AI Companion

An AI companion web app. You create companions with a personality and chat with them over a streaming reply. The companion adapts to your emotional tone and remembers durable facts about you across conversations. Replies can be spoken with built-in or cloned voices (XTTS-v2, F5-TTS or Inworld), and you can talk to it through local Whisper speech-to-text.

Stack: FastAPI, SQLAlchemy + Alembic (SQLite locally, PostgreSQL in production), OpenRouter (any OpenAI-compatible model), a DB-backed job queue for TTS, summaries and memory work, and a plain HTML/JS frontend.

See [docs/AUDIT.md](docs/AUDIT.md) for the engineering audit that drove the current architecture.

## Architecture

```
browser ──► FastAPI (app/main.py)
              │  auth (server-side sessions) · CSRF · rate limits · request IDs · JSON logs
              │
              ├─ /api/chat ──► context builder ──► OpenRouter (streaming, retries, fallback model)
              │                 persona + emotion strategy + memories + rolling summary + recent turns
              │
              └─ enqueue ──► jobs table ◄── worker (python -m jobs.worker)
                                 ├─ tts        XTTS / F5-TTS / Inworld + DSP delivery
                                 └─ background summaries · memory extraction · retention sweep

STT: /api/stt ──► validated upload ──► Whisper in a child process (CUDA runtime isolation)
```

| Area | Where |
|------|-------|
| Configuration (all env vars) | `app/core/config.py`, `app/.env.example` |
| Auth, sessions | `app/auth.py` |
| CSRF, body limits, security headers | `app/core/security.py` |
| Ownership rules (IDOR protection) | `app/core/access.py` |
| Error format `{"error": {"code", "message"}}` | `app/core/errors.py` |
| Rate limits | `app/core/rate_limit.py` |
| Upload validation | `app/core/uploads.py` |
| Chat streaming, retry/regenerate/stop | `app/routers/chat.py`, `app/conversation/` |
| Long-term memory | `app/memory/` |
| Emotion → strategy → tone → voice | `app/emotion/` |
| TTS jobs, cloning, voice storage | `app/voice/service.py`, `app/routers/speech.py`, `app/routers/voice_library.py` |
| Job queue and worker | `app/jobs/` |
| Privacy: export, deletion, retention | `app/privacy/service.py`, `app/routers/privacy.py` |
| Admin and audit log | `app/routers/admin.py`, `app/core/audit.py` |
| Migrations | `app/migrations/` |

## Run locally (development)

Requires Python 3.11.

```bash
cd app
python -m venv venv
venv\Scripts\activate            # Windows  (source venv/bin/activate on Linux/macOS)
pip install -r requirements.txt   # CPU web app + local STT
# pip install -r requirements/gpu.txt   # optional: local XTTS / F5-TTS (install CUDA torch first)
cp .env.example .env              # set OPENROUTER_API_KEY; VOICE_ENGINE=inworld needs INWORLD_API_KEY
uvicorn main:app --reload
```

Open http://127.0.0.1:8000. In development the app applies database migrations on startup (`AUTO_MIGRATE=true`) and runs the background worker inside the web process (`WORKER_MODE=embedded`), so no other services are needed. On Windows, `start.bat` and `stop.bat` still work.

First super admin: sign up, then run `python scripts/promote_admin.py you@example.com`.

Voices:
- **Inworld:** `python scripts/seed_inworld_voices.py`
- **XTTS:** `python scripts/seed_voices.py`
- **Cloned voices:** users clone their own voice in the Voice Library. To import an existing recording for a user, run `python scripts/import_voice_reference.py you@example.com path/to/voice.wav "My voice"`.

**Upgrading an existing database:** on first start, a database created before Alembic is stamped at the baseline revision and then migrated. Your data is preserved. Back up `data/app.db` first anyway.

## Tests

```bash
cd app
pip install -r requirements/dev.txt
pytest
```

The suite runs against a throwaway SQLite database using the real migrations. The LLM, TTS and STT are faked, so no network or GPU is needed.

## Run in production

```bash
cp app/.env.example .env
# set: JWT_SECRET (32+ chars), OPENROUTER_API_KEY, INWORLD_API_KEY, POSTGRES_PASSWORD, TRUSTED_HOSTS
docker compose up -d --build
```

This starts PostgreSQL, Redis (shared rate-limit counters), a one-shot `migrate` service (`alembic upgrade head`), the web app on port 8000 and a background worker.

Put a TLS-terminating reverse proxy in front: `APP_ENV=production` sets `Secure` cookies and HSTS.

- **Local GPU TTS:** the default image is CPU-only. For XTTS or F5-TTS, run the worker's `tts` queue on a CUDA host: `python -m jobs.worker --queues tts`, installed with `requirements/gpu.txt`.
- **Migrations:** production migrations are an explicit deploy step (`AUTO_MIGRATE` is off). `alembic upgrade head --sql` renders the SQL for review.
- **Health checks:** `/health/live` checks the process only, `/health/ready` checks the database and migrations, and `/health` returns a summary.
