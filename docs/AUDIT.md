# Engineering audit: AI Companion

Audit of commit `54b6720` (initial import), done before any changes were made.
Paths are relative to `app/`. Line numbers refer to that commit.

Severity: **Critical** = exploitable now or data loss; **High** = security/reliability defect
likely to bite in normal use; **Medium** = correctness/maintainability risk; **Low** = hygiene.

## 1. Security and authorization

| # | File | Line / function | Problem | Severity | Why it matters | Fix |
|---|------|-----------------|---------|----------|----------------|-----|
| S1 | routers/chat.py | 71 `chat_page`, 83 `new_chat_thread` | No ownership/visibility check on `companion_id`. Any logged-in user who knows (or guesses) the ID of a **private** companion can open it and chat with it. `new_chat_thread` doesn't even check that the companion exists. | Critical | IDOR: private companion personas (which can contain personal info) are exposed and usable by other users. | Central `can_access_companion()` (owner or public) used by every companion/conversation entry point. |
| S2 | routers/chat.py | 228 `speak_message`; routers/voice_library.py 27 `preview_voice` | Voice looked up by ID only. User A can synthesize speech with User B's **cloned voice**. | Critical | Voice cloning abuse: anyone can make another person's cloned voice say anything. | `accessible_voices_query(user)` (builtin + own voices only), used everywhere a voice is read. |
| S3 | routers/chat.py 53, settings_routes.py 15, voice_library.py 22 | voice listings | All voices, including every user's cloned voices, are listed to everyone. | High | Leaks other users' cloned voices and makes S2 trivially discoverable. | Same accessor as S2. |
| S4 | routers/settings_routes.py | 40 `update_voice_preferences` | `default_voice_id` saved without validation (any string, any other user's voice). | Medium | Stores dangling/foreign references; combined with S2 enables using another user's voice. | Validate against accessible voices. |
| S5 | static/previews + voice_library.py 34 | preview files | Previews (including the **cloned** voice preview `cloned_helly.wav`) are written under `/static`, which is served **without authentication**. | High | Anyone on the network can download cloned voice audio. | Store previews under `data/`, serve through an authenticated, ownership-checked route. |
| S6 | templates/voice_history.html | 98 | `vm.companion_name` is interpolated into `innerHTML` unescaped (and `text_preview` only escapes `<`). Companion names come from other users for public companions. | High | Stored XSS: a public companion named `<img src=x onerror=...>` runs script in every viewer's session. | Escape every interpolated value (shared `escapeHtml`). |
| S7 | all POST/DELETE routes | — | No CSRF protection. `SameSite=Lax` helps but doesn't cover same-site subdomains, older browsers, or login CSRF. | High | State-changing requests (role changes, deletes, settings) can be forged. | Double-submit CSRF token (cookie + form field/header), enforced by a global dependency on every unsafe method. |
| S8 | auth.py | 28 `create_session_token`; routers/auth_routes.py 69 `logout` | Stateless 7-day JWT; logout only deletes the cookie, so a stolen token stays valid for 7 days. No revocation on role change or account deletion. | High | Session theft / leakage has no mitigation. | Server-side `user_sessions` table; JWT carries a session ID; logout/role change/account delete revoke it. Session rotated on login. |
| S9 | routers/auth_routes.py | 33, 65 `set_cookie` | Cookie never `Secure`. | High (prod) | Session cookie sent over plain HTTP in production. | `Secure` when `APP_ENV=production`; configurable. |
| S10 | auth.py | 12 | `JWT_SECRET` has no strength check; any value (even 1 char) accepted. | Medium | Weak secret = forgeable sessions. | Config validation: ≥32 chars required in production. |
| S11 | routers/auth_routes.py | 20 `login_submit`, 44 `signup_submit` | No rate limiting, no email validation/normalisation (`A@x.com` and `a@x.com` are different accounts), password min 6, no max (bcrypt silently truncates at 72 bytes). | High | Credential stuffing / brute force; duplicate accounts. | Central rate limiter; `EmailStr` + lower-casing; password 8–72 bytes. |
| S12 | routers/chat.py | 313 `api_stt` | Whole upload read into memory with no size limit, no content-type/magic-byte check, no duration limit, subprocess return code and stderr ignored, errors return `{"text": ""}`. | Critical | Trivial memory/disk DoS; crashes look like "empty transcript". | Streamed upload with size cap, magic-byte sniffing, duration probe (PyAV), concurrency cap, return-code/timeout handling, `finally` cleanup, typed API errors. |
| S13 | routers/admin.py | 34 `update_role` | Super-admin can demote the last other super-admin (lock-out); role changes aren't audited; silent redirect on invalid input. | Medium | No accountability for privilege changes. | `audit_logs` table (actor, target, action, before, after, timestamp); last-super-admin guard. |
| S14 | schemas.py | all | No length limits on message, title, companion name/description, IDs. | Medium | Unbounded prompts cost money; huge rows. | Pydantic constraints; server-side limits in config. |
| S15 | voice/xtts.py 12, train_classifier.py 26, data/inworld_voice_cache.json | constants | Hard-coded machine paths (`D:/#practicals/AI companion/...`). The repo has since moved, so the cloned voice reference is **already broken** on this machine. The Inworld clone cache is keyed by absolute path. | High | Voice cloning breaks on any other machine/deploy; paths leak in DB and cache. | Voice reference files stored under a configured storage dir, referenced by relative key in the DB; provider voice IDs stored on the `voices` row. |

## 2. Reliability and data integrity

| # | File | Line / function | Problem | Severity | Why it matters | Fix |
|---|------|-----------------|---------|----------|----------------|-----|
| R1 | database.py | 10 | SQLite `PRAGMA foreign_keys` never enabled, so every `ondelete="CASCADE"` in models.py is **ignored**. | Critical | Deleting a conversation/user leaves orphaned messages, voice messages, emotional memory. | Enable the pragma on connect; ORM cascades added too. |
| R2 | routers/conversations.py | 93 `delete_conversation` | Deletes the row but never removes the generated `.wav` files on disk. | High | Sensitive audio survives "delete". | File cleanup through a storage helper after commit. |
| R3 | main.py | 20 | `Base.metadata.create_all` is the only schema mechanism; column additions are one-off scripts (`scripts/add_voice_adaptive_columns.py`). | High | Cannot evolve schema safely; no path to PostgreSQL. | Alembic with a baseline revision matching the existing DB, plus a revision for the new schema. Existing DBs are stamped automatically. |
| R4 | routers/chat.py | 184 `generate` | On LLM error the stream just stops; the assistant row is saved as `"[no reply generated]"`, which is then fed back to the model as history. No status field. | High | Garbage in context, silent failures, no retry path. | `messages.status` (pending/streaming/completed/failed/cancelled) + `error_code`; failed/empty replies are excluded from context; retry/regenerate endpoints. |
| R5 | llm/openrouter.py | all | No timeout, no retry, no fallback model, no `max_tokens`, raw provider exceptions. Client created at import (crashes import without the key). | High | One provider hiccup = broken chat; unbounded cost. | Timeouts, retries with exponential backoff before first token, fallback models, token cap, normalised `LLMError`. |
| R6 | routers/chat.py | 171 `history` | Entire conversation history is sent on every turn. | High | Cost and latency grow without bound; eventually exceeds context window and every request fails. | Token-budgeted context: recent window + rolling summary + retrieved memories + emotion strategy + persona. |
| R7 | routers/chat.py | 251 `speak_message` | TTS (seconds of GPU work, or a paid API call) runs inside the request. | High | Ties up request workers; timeouts; no cancellation. | DB-backed job queue with `queued/processing/completed/failed/cancelled`; embedded worker in dev, separate worker process in prod. |
| R8 | routers/chat.py | 251–283 | Any engine/DSP exception becomes an unhandled 500 with a stack trace in the log and a generic error to the user; raw file may be left behind. | Medium | Leaks internals; disk litter. | Job-level error capture with error codes; temp cleanup in `finally`. |
| R9 | voice/engines/*.py | `_ref_text_for`, `_transcribe_for_clone` | STT subprocess failures are silently cached/ignored (`lru_cache` caches an empty transcript forever). | Medium | F5-TTS clones silently degrade. | Shared hardened `run_transcription()`; failures raise and are not cached. |
| R10 | routers/voice_messages.py | 55 | `audio_path` absolute paths stored in DB. | Medium | Breaks when data dir moves; leaks paths. | Store paths relative to the data dir. |
| R11 | emotion/classifier.py | 28 | Returns only a label; keyword override *pre-empts* the model; no confidence. | Medium | Can't gate on certainty; "stressed" beats clear model predictions. | `EmotionResult(emotion, confidence, source)`; keywords used as fallback / low-confidence override. |
| R12 | voice/adaptive.py | 84 | Voice preset mirrors the emotion of the reply text / user; e.g. angry reply ⇒ "angry" voice. | Medium | Companion can sound aggressive when user is angry. | Explicit pipeline: user emotion → response strategy → assistant tone → voice delivery. |

## 3. Maintainability, observability, deployment

| # | File | Problem | Severity | Fix |
|---|------|---------|----------|-----|
| M1 | everywhere | Config read ad hoc via `os.environ` in 5 modules; `auth.py` and `llm/openrouter.py` crash on import without env vars. | Medium | `core/config.py` single settings object with validation. |
| M2 | everywhere | Inconsistent error bodies (`{"error": "..."}`, plain text, HTML, redirects). | Medium | `AppError` + handlers ⇒ `{"error": {"code", "message"}}`; no stack traces/paths in responses. |
| M3 | — | No logging, no request IDs, no health checks. | Medium | JSON logs, `X-Request-ID`, `/health`, `/health/live`, `/health/ready`. |
| M4 | requirements.txt | `pip freeze` of a partial env: missing `librosa`, `soundfile`, `langdetect`, `requests`, `coqui-tts`, `torch`; includes Windows-only `pywin32`/`pypiwin32`/`comtypes`/`pyttsx3`, unused `passlib`, `pandas` (training only). A Linux install fails; a fresh install can't run the app. | High | Split into `requirements/{base,stt,gpu,windows,dev,production}.txt`. |
| M5 | voice/tts.py | Dead pyttsx3 module (nothing imports it). | Low | Removed. |
| M6 | static/js/chat.js | 394-line IIFE mixing streaming, audio, STT, sidebar, conversations; errors only in `console`. | Medium | Split into ES modules; visible error/loading/cancel states. |
| M7 | — | No tests. | High | pytest suite focused on security boundaries. |
| M8 | — | No long-term memory, no privacy controls, no export/delete. | Medium | Memory tables + extraction/retrieval; privacy settings; export and delete endpoints. |
| M9 | — | No container/production story; Windows-only `.bat` scripts. | Medium | Dockerfile + docker-compose (Postgres, web, worker). |

## Verified as correct (kept as-is)

- Conversation/message/voice-message endpoints in `routers/conversations.py` and `routers/voice_messages.py` already scope by `Conversation.user_id`, so there's no IDOR there.
- `/admin/roles` correctly requires `super_admin`; self-role-change is blocked.
- Passwords use bcrypt with per-hash salt.
- Chat page templates rely on Jinja autoescaping (safe); `chat.js` escapes sidebar data.
- The STT subprocess isolation (ctranslate2 vs torch CUDA runtime clash) is a real constraint and is kept.
- DSP effect design (resample-based speed) is deliberate and documented; unchanged.
