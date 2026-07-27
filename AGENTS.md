# TermSub — Agent Guide

This file is a concise, accurate reference for AI coding agents working on TermSub. All information below is derived from the actual codebase (Python files, configuration, tests, CI, and deployment manifests).

## Project Overview

TermSub is an AI-powered web application for translating video content with terminology management. It is built as a Python 3.11+ FastAPI backend with a vanilla-JS frontend, SQLAlchemy 2.0 ORM, PostgreSQL, Redis, and Celery workers.

The product's distinguishing feature is a **terminology-first translation pipeline**: before translating, the system extracts and locks key terms (names, brands, technical terms) so they stay consistent across all subtitles and all supported target languages.

### Core Capabilities

- **Upload** video, audio, or text files (`.mp4`, `.mov`, `.mp3`, `.txt`, `.srt`, `.vtt`, etc.). Max file size is 500 MB.
- **Transcribe** via OpenAI `whisper-1` after FFmpeg audio extraction (16 kHz mono MP3).
- **Analyze** with a multi-agent pipeline:
  1. **Director Agent** — generates a style guide (tone, formality, domain, audience).
  2. **Glossary Agent** — extracts key terms and proposes translations.
  3. **Translator Agent** — performs sliding-window translation using the glossary and full-transcript context.
- **Review** extracted terms, edit subtitles inline, split/add/remove segments, and run global find/replace.
- **Transcript review checkpoint** (opt-in, default on): after transcription, users can review/edit the raw transcript before analysis/translation starts. Segments Whisper was unsure about are flagged using `avg_logprob`/`no_speech_prob` captured at transcription time (`Segment.avg_logprob`, `Segment.no_speech_prob`). This is gated client-side by a `reviewTranscript` config flag, not a new `VideoStatus` value — the pipeline still pauses at `TRANSCRIBED`.
- **Export** subtitles as SRT, WebVTT, TXT, or JSON (plus original transcription SRT).
- **Skip terminology mode** (`skip_glossary`) lets users bypass analysis and translate directly.
- **Text-only pipeline**: a parallel pipeline for plain text/SRT/VTT documents (`ContentType.TEXT`) that skips audio/transcription entirely — extract terms and translate text directly. Served by `app/api/text_translation.py` (mounted at `/api/text`), not `app/api/videos.py`.

### Language Support

The app supports **59 source and target languages**, enumerated in `app/core/languages.py`. The list combines OpenAI Audio API-supported languages with a small set of legacy additions. Persian (Farsi) and RTL languages are first-class use cases.

### High-Level Architecture

```
Frontend (vanilla JS + Tailwind CDN)
    │
FastAPI app (app/main.py)
    ├── REST API routers (app/api/)
    ├── WebSocket /ws/videos/{id} progress feed
    └── Redis Pub/Sub listener forwards worker progress to WebSockets
    │
Celery worker (app/worker/tasks.py)
    ├── transcribe_video_task
    ├── analyze_video_task
    └── translate_video_task
    │
PostgreSQL  (Video, Segment, Term, User, JobQueue, analytics, etc.)
Redis       (Celery broker/result backend, rate limits, token revocation, quota state)
OpenAI      (whisper-1 transcription, gpt-5.4-mini analysis/translation)
FFmpeg      (audio extraction)
```

### Video Status Pipeline

```
UPLOADED → QUEUED → EXTRACTING_AUDIO → TRANSCRIBING → TRANSCRIBED
→ ANALYZING → CONTEXT_READY → GLOSSARY_EXTRACTING → TERMS_READY
→ TRANSLATING → COMPLETED
```

Errors land in `ERROR`. When `skip_glossary=True`, the pipeline jumps from `TRANSCRIBED` directly to `TRANSLATING`. When the transcript-review checkpoint is enabled (default), the frontend pauses at `TRANSCRIBED` until the user confirms the transcript, tracked client-side (`transcriptReviewConfirmed` in job-session config), not as a DB status.

The text-only pipeline reuses the same status enum but drives it through `app/worker/text_tasks.py` instead of `app/worker/tasks.py`; its Celery job rows use the free-form `job_type` values `"text_analyze"` / `"text_translate"` (a raw SQL `CHECK` constraint in `job_queue`, not the `JobType` StrEnum, which still only covers `transcribe`/`analyze`/`translate` for the video pipeline).

## Repository Layout

```
app/
  main.py                  # FastAPI entry point, lifespan, WebSocket, static routes
  api/                     # FastAPI routers (thin: validate + dispatch)
    auth.py                # Login, signup, password reset, verification, logout, ws-token
    videos.py              # Upload, transcribe, analyze, translate, segment CRUD (video pipeline)
    text_translation.py    # Extract-terms/translate/export for the text-only pipeline (`/api/text`)
    terms.py               # Term CRUD and standardization
    export.py              # SRT/VTT/TXT/JSON export
    progress.py            # Progress/logs endpoints
    jobs.py                # Job history list + single-job detail (`/jobs`)
    admin.py               # Admin user/quota endpoints
    profile.py             # Profile and account deletion
    quota.py               # Quota status endpoint
  services/                # Business logic and pipeline orchestration
    whisper_service.py     # FFmpeg extraction + OpenAI transcription orchestration
    transcription.py       # OpenAI whisper-1 client, chunking, segment merge, confidence capture
    context_analysis_service.py  # Director + Glossary agents (video pipeline)
    translation_pipeline.py      # Multi-agent pipeline class + Pydantic schemas (video pipeline)
    text_translation_service.py  # Term extraction + translation orchestration (text pipeline)
    gemini_service.py      # Historical wrapper; all LLM logic is now OpenAI
    upload_service.py      # File validation, sanitization, saving
    text_parser.py         # Text/SRT/VTT ingestion for the text pipeline
    progress_service.py    # Progress tracking DB writes
  agents/
    translator.py          # Sliding-window OpenAI translator agent, video pipeline (DB-free core)
    text_translator_agent.py  # Sliding-window translator agent, text pipeline
    text_context_agent.py     # Style-guide/glossary agent, text pipeline
  core/                    # Config, auth, quota, rate limiting, Celery, Redis pub/sub
    config.py              # Pydantic settings; rejects weak JWT secrets at import
    celery_app.py          # Celery + Redis configuration
    redis_pool.py          # Shared sync/async Redis connection pools
    redis_pubsub.py        # Redis Pub/Sub bridge for worker → WebSocket progress
    auth.py                # JWT, password hashing, current-user/BYOK dependency, ws tokens
    quota.py               # Trial-minute and BYOK abuse-limit enforcement via Redis
    rate_limit.py          # Sliding-window Redis rate limiter
    email.py               # Resend-backed transactional email helpers
    openai_key_context.py  # ContextVar for BYOK API keys
    languages.py           # 59-language code/name map
  models/                  # SQLAlchemy 2.0 models
    video.py               # Video, Segment (incl. avg_logprob/no_speech_prob), Term, TermOccurrence, TranslationVariant, ProcessingLog
    user.py                # User, UserSession
    job_queue.py           # JobQueue, JobStatus, JobType (video pipeline only; text pipeline uses raw job_type strings)
    analytics.py           # PageView, UsageEvent
    newsletter.py          # Newsletter signup
  db/                      # Engine, SessionLocal, base, session helpers
    base.py                # SQLAlchemy Base
    session.py             # Engine, SessionLocal, get_db, bulk helpers
    session_utils.py       # get_db_session context manager + short-session helpers
  schemas/                 # Pydantic request/response models
  worker/
    tasks.py               # Celery task implementations, video pipeline
    text_tasks.py          # Celery task implementations, text pipeline
frontend/                  # Static HTML/JS/CSS served by FastAPI; no build step
  index.html              # Main app (upload/review/translate wizard)
  admin.html              # Admin dashboard
  landing.html, contact.html  # Marketing pages
  legal/                  # Privacy, beta terms, AI disclosure, imprint
  js/main.js              # Primary app logic, WebSocket handling, wizard steps
  js/jobSession.js        # Per-video job-session config persisted client-side
  js/textPipeline.js      # Text-pipeline-specific UI wiring
alembic/                   # Alembic migrations (sole source of truth; `start.sh` runs `alembic upgrade head` on boot)
tests/                     # pytest suite; hits real Postgres + Redis
scripts/                   # make_admin.py, seed_admin.py
```

## Technology Stack

- **Backend**: FastAPI 0.115, Starlette 0.38, Uvicorn 0.32, SQLAlchemy 2.0, Pydantic 2.9, Pydantic-Settings
- **Database**: PostgreSQL 15 (production/Docker), SQLite fallback possible for some helpers
- **Migrations**: Alembic 1.14
- **Queue/Cache**: Celery 5.4 + Redis 5.2
- **AI/ML**: OpenAI Python SDK 1.65 (`whisper-1`, `gpt-5.4-mini`)
- **Audio**: FFmpeg (system dependency)
- **Auth**: passlib/bcrypt, PyJWT 2.10
- **Email**: Resend
- **Frontend**: Vanilla JS, Tailwind CSS via CDN, no build step
- **Code Quality**: Ruff (lint + format), MyPy strict (CI also installs `types-passlib` for passlib stubs)
- **Testing**: pytest

## Build, Run, and Test Commands

### Initial Setup

```bash
# Create venv and install pinned dependencies
./setup_env.sh
source venv/bin/activate
```

`setup_env.sh` creates a Python 3.11+ virtual environment, installs `requirements.txt`, and verifies critical imports.

### Environment Configuration

Copy `.env.example` to `.env` and fill in required values:

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENAI_API_KEY` | Yes | Used for transcription, analysis, and translation unless BYOK. |
| `DATABASE_URL` | Yes | PostgreSQL URL; default in example is Docker service name `db`. |
| `REDIS_URL` | No | Defaults to `redis://redis:6379/0`. |
| `JWT_SECRET_KEY` | Yes | Must be strong and random; app refuses weak/default secrets. |
| `FRONTEND_BASE_URL` | Yes | CORS origin; default `http://localhost:8000`. |
| `RESEND_API_KEY` | No | Leave blank to disable email. |

### Run Locally

You need PostgreSQL and Redis running. The easiest local path is Docker Compose.

#### Docker Compose (recommended)

```bash
docker compose up --build
```

This starts a `migrate` service (waits for Postgres, then runs `alembic upgrade head`), `web` (FastAPI, `uvicorn --reload`), `worker` (Celery), `db` (Postgres 15), and `redis`.

#### Manual / Development

Terminal 1 — Celery worker:

```bash
celery -A app.core.celery_app worker --loglevel=info --concurrency=2
```

Terminal 2 — FastAPI:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The web UI is at `http://localhost:8000`. API docs are at `/docs` and `/redoc`.

#### Production Entrypoint

`start.sh` runs `alembic upgrade head`, starts the Celery worker in the background, and then starts Uvicorn. This is the single-container entrypoint used by both `Dockerfile`/Railway (the live target) and the still-present `render.yaml` — see Deployment below.

### Tests

The test suite uses real infrastructure; there is no in-process SQLite/mocked DB for the whole suite.

```bash
pytest
pytest tests/test_translator.py              # single file
pytest tests/test_translator.py::test_name   # single test
pytest -k "quota" -v                         # keyword filter
```

Requirements for tests:
- `DATABASE_URL` must point to a reachable Postgres (`.env.local` uses `localhost:5432`).
- Redis must be reachable.
- `conftest.py` creates real `User` rows and clears Redis keys (`rate_limit:*`, `revoked_token:*`, `resend_cooldown:*`) between tests.
- The `auth_headers` / `authenticated_user` fixtures mint valid JWTs.

### Code Quality

`.github/workflows/ci.yml` runs all three on every push/PR to `main` and blocks merge on failure:

```bash
pip install ruff mypy types-passlib
pip install -r requirements.txt
ruff check .
ruff format --check .     # use `ruff format .` to auto-fix
mypy app/ --config-file pyproject.toml
```

**Verify locally against a venv that matches `requirements.txt`, not your ambient environment.** An ambient/global Python environment can have newer package versions than the pins in `requirements.txt` (e.g. `redis`, `fastapi`, `starlette`) — those newer versions can ship different or more complete type stubs, so `mypy`/`ruff` can pass locally and still fail in CI (or vice versa) purely from a version mismatch, with no code difference. Before trusting a local "clean" result, build a disposable venv the same way CI does:

```bash
python3.11 -m venv /tmp/ci_venv   # match .github/workflows/ci.yml's Python version
/tmp/ci_venv/bin/pip install -r requirements.txt
/tmp/ci_venv/bin/pip install ruff mypy types-passlib
/tmp/ci_venv/bin/mypy app/ --config-file pyproject.toml
```

MyPy runs in **strict** mode over `app/` only. New code must be fully type-annotated.

- **Missing/incomplete stubs for a whole module** (e.g. celery, openai, ffmpeg): exempt in `pyproject.toml` under `[[tool.mypy.overrides]] / ignore_missing_imports = true` — extend that list rather than sprinkling `# type: ignore`.
- **A specific untyped call on an otherwise-typed module** (e.g. `redis.ConnectionPool.from_url()`, `Pipeline.execute()` in the pinned `redis==5.2.0`): `ignore_missing_imports` does **not** silence this — the import resolves fine, only that one function lacks annotations, so mypy still raises `no-untyped-call` under strict mode. Use a targeted `# type: ignore[no-untyped-call]` on that line instead (see `app/core/redis_pool.py`, `app/core/quota.py`).
- **A third-party function typed to return `Any`** (e.g. `jwt.decode()`, `resend.Emails.send()`): cast to the real runtime shape at the call site — `cast("dict[str, Any]", jwt.decode(...))` — rather than loosening the function's own return type. Several examples are in `app/core/auth.py`, `app/core/quota.py`, `app/core/email.py`.
- `passlib` has real published stubs (`types-passlib`) as of this writing — install them rather than adding `passlib.*` to the ignore-imports list.

## Database Migrations

`alembic/` is the **sole** migration system — the legacy standalone `migrations/` scripts and the old `Base.metadata.create_all()` / `ensure_schema()` startup safety nets have been removed. `start.sh` (the production entrypoint) runs `alembic upgrade head` automatically on every boot, including on Railway deploys.

For a fresh or existing Postgres database:

```bash
alembic upgrade head
```

To create a new revision after editing models:

```bash
alembic revision --autogenerate -m "describe change"
```

## Operational Guardrails

### No Pushes Without Explicit Confirmation

AI agents must **never** run `git push`, `git push --force`, `git push --force-with-lease`, or any other command that sends local git history or changes to the remote repository without first obtaining explicit, per-push confirmation from the user. This includes pushing new commits, tags, branches, or rewritten history. The user must approve the exact action before it is executed.

## Development Conventions

### FastAPI Router Pattern

Routers in `app/api/` are intentionally thin: validate input, enforce quota/ownership, dispatch Celery tasks with `.delay(...)`, and return immediately. Heavy work (audio extraction, transcription, translation) never runs inline in the API process.

### Background Jobs and Progress

Long-running work is performed by Celery tasks in `app/worker/tasks.py` (video pipeline):
- `transcribe_video_task`
- `analyze_video_task`
- `translate_video_task`

The text pipeline has its own equivalents in `app/worker/text_tasks.py`: `extract_text_terms_task`, `translate_text_task`.

Tasks publish progress via `publish_progress()` in `app/core/redis_pubsub.py`. The FastAPI lifespan starts an async Redis Pub/Sub listener (`start_redis_listener`) that forwards those messages to connected WebSocket clients on `/ws/videos/{video_id}`.

**Critical rule**: Workers must publish progress through Redis. They must **not** push directly to WebSockets, because workers and the web process are separate processes/containers.

### Database Session Hygiene

Long-running work must **not** hold an open DB session, to avoid lock contention. Use `get_db_session()` from `app/db/session_utils.py` as a short-lived `with` block. Pass **primitives** out of the session; never pass detached ORM objects.

Preferred pattern (see `get_video_with_session`):

```python
with get_db_session() as db:
    video = db.query(Video).filter(Video.id == video_id).first()
    file_path = video.file_path
    target_language = video.target_language
# do long work with primitives, then open a new session to save
```

Celery tasks deliberately open and close several short sessions around long OpenAI calls rather than holding one long session.

### Authentication

Two identity types resolve through `get_current_user_or_byok` into a `RequestIdentity`:

1. **Standard users** — `Authorization: Bearer <jwt>`. JWTs are signed with `JWT_SECRET_KEY`, expire in 7 days, and include a `jti` that can be revoked in Redis (`revoked_token:{jti}`). Users must have a verified email and active account.
2. **BYOK (bring your own key)** — `X-API-Key: <openai-key>`. The key's SHA-256 hash is the user id. BYOK bypasses trial-minute quotas but is subject to abuse limits.

The chosen API key flows: endpoint → Celery task arg → `byok_api_key` ContextVar (`app/core/openai_key_context.py`) → picked up by OpenAI client factories (`get_effective_openai_key`).

WebSocket authentication uses subprotocols to avoid putting credentials in the URL:
- Standard: `["termsub-ws-token", <short-lived-ws-token>]` — the client first calls `POST /api/auth/ws-token` (rate-limited, requires a valid JWT) to mint a 60-second-lived token via `create_ws_token`/`decode_ws_token`, then opens the socket with that token, not the long-lived access JWT itself.
- BYOK: `["termsub-byok", <openai-api-key>]`

### Quota and Rate Limits

- Standard users: lifetime trial of 30 transcribed audio minutes, tracked in Redis (`quota:{user_id}:minutes`). Uploads atomically reserve estimated minutes; the worker reconciles with actual duration after transcription.
- BYOK users: 500 MB max upload, 10 max concurrent jobs, job heartbeat every 60 seconds.
- Rate limiting uses Redis sorted sets (`rate_limit:{endpoint}:{ident}`). It currently defaults to IP-based identifiers and fails open if Redis is unavailable.

### Frontend

There is no build step. Static HTML files in `frontend/` are served directly by routes in `app/main.py`, and `/static` is mounted for CSS/JS/assets. `/app/{path}` and `/admin/{path}` are catch-all deep-link routes.

## Code Style Guidelines

Configuration lives in `pyproject.toml`:

- **Ruff**: target Python 3.11, line length 88, double quotes, spaces, Google docstring convention.
- **Selected rules**: E, F, I, W, N, UP, B, C4, SIM.
- **Ignored**: B008 (FastAPI `Depends()` in default args is idiomatic).
- **MyPy**: strict mode for `app/`.

Project-specific style conventions observed in the code:
- Use type annotations everywhere; avoid bare `Any` unless necessary.
- Use Google-style docstrings.
- Prefer `from pathlib import Path` for filesystem paths.
- Prefer f-strings.
- Use SQLAlchemy 2.0 `Mapped[...]` / `mapped_column(...)` style in models.
- Use `StrEnum` for status/value enums.
- Use `datetime.utcnow()` for DB timestamps (current convention, though timezone-aware datetimes would be preferable for new code).
- Keep routers thin; put business logic in `app/services/`.
- Use `print()` for ad-hoc operational logging in many modules; structured `logging` is also present in Celery tasks.

## Testing Instructions

- Run the full suite with `pytest`.
- Tests require a real PostgreSQL database and Redis.
- Use `.env.local` for local test DB configuration if needed (it overrides Docker service names with `localhost`).
- The translator agent tests (`tests/test_translator.py`) use mocked OpenAI clients and `pytest-anyio` with `asyncio` backend only.
- Export tests (`tests/test_export.py`) mix TestClient integration tests with in-memory SQLite unit tests.
- When adding features, add tests in `tests/` mirroring the existing patterns.

## Security Considerations

The following are current security facts and known risks agents should be aware of. Refer to `docs/codebase-review.md` (2026-07-10, full backend/frontend/worker/deployment audit with file:line citations and severity ratings) for the fuller report — several of its findings have since been fixed (noted below); treat the doc itself as a point-in-time snapshot, not a live tracker.

### Current Defenses

- Passwords hashed with bcrypt via passlib; signup enforces 8-character minimum.
- `JWT_SECRET_KEY` must be strong/random; weak/default secrets are rejected at startup (`app/core/config.py`).
- File uploads enforce extension whitelisting, 500 MB size limit, and MIME validation via `python-magic`.
- SQL queries use SQLAlchemy parameter binding; raw SQL in endpoints is parameterized.
- CORS is restricted to a single configured origin with `allow_credentials=False`.
- Token revocation blocklist stored in Redis by JWT ID (`jti`).
- Global session invalidation via `user.sessions_invalidated_at`, including automatically on password change (`app/api/profile.py::update_password`, `app/api/auth.py` reset flow).
- Email verification and password-reset tokens are hashed (`hash_token`, SHA-256) before storage in `users.email_verification_token` / `users.password_reset_token` — the raw token only ever exists in the emailed link.
- `(video_id, sequence_number)` has a `unique=True` index (`idx_segments_video_seq` in `app/models/video.py`) — collisions are now rejected at the DB level.
- Security headers middleware (`SecurityHeadersMiddleware` in `app/main.py`) sets CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, and HSTS (on HTTPS requests).
- Single migration system: `alembic/` only (see Database Migrations above) — no more parallel `Base.metadata.create_all()`/`ensure_schema()` startup patching.

### Known Risks (Do Not Reinvent Without Addressing)

- **DOM XSS**: `frontend/js/main.js` and `frontend/admin.html` use `innerHTML`/`insertAdjacentHTML` with server-controlled strings in the activity log, toast system, admin tables, and job lists. Dynamic text should be escaped or created as DOM nodes. Still present as of this writing.
- **Credentials in localStorage**: The frontend stores JWT and BYOK OpenAI key in `localStorage`, making them vulnerable to XSS/browser extensions.
- **BYOK keys in Celery kwargs**: User OpenAI keys are still passed as a plain `api_key` argument into Celery task calls (`app/worker/tasks.py`, `app/worker/text_tasks.py`), i.e. serialized into Redis broker messages. They should be passed via short-lived one-time Redis tokens instead.
- **Upload filename collisions**: `generate_unique_filename()` (`app/services/upload_service.py`) uses timestamp prefixes; two uploads in the same second with the same base name can collide.
- **WebSocket ownership check**: `/ws/videos/{video_id}` authenticates the caller's identity (see Authentication above) but does not verify that identity owns the specific `video_id` before accepting the connection.
- **Rate-limit identifier**: `app/core/rate_limit.py` uses raw `request.client.host`, which is the proxy IP behind a reverse proxy, and fails open on Redis errors.
- **Unbounded admin operations**: `POST /admin/users/bulk-delete` and the per-user quota-update endpoint are gated behind `require_admin_user` but still lack an explicit batch-size cap or confirmation step.

When making changes, do not introduce new instances of these patterns, and prefer fixing them when the change touches related code.

## Deployment

- **Docker**: `Dockerfile` is Python 3.11-slim with FFmpeg and libmagic. `docker-compose.yml` defines separate `web` and `worker` services plus Postgres and Redis — this is the local dev stack (`termsub_root-web-1`, `termsub_root-worker-1`, `termsub_root-db-1`, `termsub_root-redis-1`).
- **Railway is the live production target.** The GitHub repo is linked to a Railway project (`checkSuites: false`, so GitHub Actions CI and the Railway deploy are independent — a red CI run does not by itself block or cause a Railway deploy failure, and vice versa); pushing to `main` auto-triggers a build and deploy of the `web` service, which runs `start.sh` (→ `alembic upgrade head`, then Celery worker + Uvicorn) via the same `Dockerfile`. Deploys occasionally sit `QUEUED` for several minutes with `queuedReason: "Deployment queued due to upstream GitHub issues"` before clearing on their own — a known, transient, infrastructure-side delay, not a code or config problem.
- **`render.yaml`** (a Docker web service `termsub-web` + a free Postgres database) is still present in the repo but is **not** the active deployment as of this writing — don't assume changes need to satisfy Render-specific constraints unless told otherwise. It also does not define a `healthCheckPath`; the `/health` endpoint exists if it's ever revived.

## Useful Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Health check |
| `GET /api/version` | App version from `settings.VERSION` |
| `POST /videos/upload` | Upload video/audio file; requires `target_language` |
| `POST /videos/{id}/transcribe` | Queue transcription |
| `POST /videos/{id}/analyze` | Queue Director + Glossary analysis |
| `POST /videos/{id}/translate` | Queue translation |
| `POST /videos/{id}/translate-direct` | Set `skip_glossary=True` and queue translation |
| `POST /api/text/{id}/extract-terms` | Queue term extraction for the text pipeline |
| `POST /api/text/{id}/translate` | Queue translation for the text pipeline |
| `GET /api/text/{id}/segments` | Fetch text-pipeline segments |
| `GET /api/text/{id}/terms` | Fetch text-pipeline terms |
| `POST /api/text/{id}/export` | Export text-pipeline translation |
| `GET /jobs/` | List the current user's job history |
| `GET /jobs/{id}` | Fetch a single job's detail |
| `POST /api/auth/ws-token` | Mint a short-lived token for WebSocket auth (rate-limited) |
| `GET /export/{id}/srt` | Download SRT |
| `GET /export/{id}/vtt` | Download WebVTT |
| `GET /export/{id}/txt` | Download translated text |
| `GET /export/{id}/json` | Download full JSON |
| `WS /ws/videos/{id}` | Real-time progress; requires `["termsub-ws-token", <token>]` or `["termsub-byok", <key>]` subprotocol |

## Version Notes

- `pyproject.toml` declares version `2.0.0`.
- `app/core/config.py` declares `VERSION = "2.1.0"`, which is what the running app returns from `/api/version`.
- Treat the runtime value in `config.py` as the effective version when making version-dependent decisions.
