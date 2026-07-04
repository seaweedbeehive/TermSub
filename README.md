# TermSub

> **Subtitles that get the details right.**

TermSub is an open-source, AI-powered video translation and subtitle editor. It extracts your key terminology — names, brands, technical terms — before translating, so they stay consistent across every scene and every language. Built for documentaries, research, education, and technical content.

[Start Translating Free — 30 min trial](/app) · [View on GitHub](https://github.com/seaweedbeehive/TermSub)

Live app: **https://www.termsub.eedbee.app**

---

## Built for content where details matter

- **Documentaries & Interviews** — Names, places, and institutions stay consistent across every scene and every language.
- **Educational Videos** — Complex concepts and specialized vocabulary are translated accurately every time.
- **Research & Lectures** — Technical terms, theories, and citations keep their precise meaning in translation.
- **Technical Content** — Product names, APIs, and industry jargon are preserved exactly where they belong.
- **Political, Social & Historical Content** — Ideological terms, movement names, historical references, and sociological concepts keep their precise meaning and context across languages.
- **Feature Films** — Even long-form content stays coherent. TermSub understands genre and context, so characters, locations, and tone translate naturally from opening scene to credits.

---

## Features

- **Terminology-first translation** — Before translating, TermSub identifies names, brands, and technical terms — then locks them in.
- **59 languages** — English, Spanish, French, German, Persian (Farsi), Arabic, Hebrew, Japanese, Korean, Hindi, and 49 more.
- **RTL support** — Full right-to-left support for Persian, Arabic, and Hebrew with proper text rendering and subtitle formatting.
- **Whole-video context** — TermSub reads the entire transcript before translating. Tone, style, and terminology stay coherent — start to finish.
- **Editable subtitle cards** — Review, edit, split, merge, and fine-tune every subtitle card before exporting.
- **You stay in control** — Upload, review terminology, edit subtitles, export. A feature film in under 10 minutes — with you making the decisions.

### Export Formats

- **SRT** — SubRip subtitles with RTL punctuation fixes
- **WebVTT** — HTML5 video subtitles
- **TXT** — Plain translated text
- **JSON** — Full metadata + all segments
- **Original Transcription SRT** — Pre-translation subtitles

---

## How it works

1. **Upload your video** — TermSub extracts audio and transcribes with OpenAI Whisper.
2. **Review your terminology** — AI identifies names, brands, and key terms. You approve or edit them. This is the step other tools skip.
3. **Translate & export** — Full-context translation to 59 languages. Export as SRT, VTT, TXT, or JSON.

---

## Architecture

```
                          FFmpeg              OpenAI
  Upload (Video)  ──▶  Audio Extraction  ──▶  whisper-1
                                                  │
                                                  ▼
                                        Segment Timestamps
                                                  │
                                                  ▼
                                       ┌──────────────────┐
                                       │    PostgreSQL    │◀────┐
                                       │     Database     │     │
                                       └────────┬─────────┘     │
                                                │               │
                                                ▼               │
                                       ┌──────────────────┐     │
                                       │  Celery Worker   │     │
                                       │  + Redis Broker  │     │
                                       └────────┬─────────┘     │
                                                │               │
                                                ▼               │
                                       ┌──────────────────┐     │
                                       │  Redis Pub/Sub   │─────┘
                                       │  WebSocket Feed  │
                                       └──────────────────┘
                                                │
                                                ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                    Multi-Agent Translation Pipeline                │
  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐  │
  │  │Director Agent│──▶│Glossary Agent│──▶│   Translator Agent   │  │
  │  │  Style Guide │   │Term Extraction│  │Sliding-Window Translate│ │
  │  └──────────────┘   └──────────────┘   └──────────────────────┘  │
  └──────────────────────────────────────────────────────────────────┘
                                                │
                                                ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  Terminology Review  │  Subtitle Timeline (Edit / Find & Replace) │
  └──────────────────────────────────────────────────────────────────┘
                                                │
                                                ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │              Export (SRT / VTT / TXT / JSON)                      │
  └──────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
├── app/
│   ├── agents/               # Standalone AI agent modules
│   ├── api/                  # FastAPI routers
│   ├── core/                 # Config, Celery, Redis, auth, rate limits
│   ├── db/                   # SQLAlchemy base, session, utilities
│   ├── models/               # SQLAlchemy models
│   ├── schemas/              # Pydantic request/response models
│   ├── services/             # Business logic and pipeline orchestration
│   └── main.py               # FastAPI app + WebSocket + built-in UI
├── alembic/                  # Database migrations
├── frontend/                 # Static UI assets (JS + Tailwind CSS)
├── uploads/                  # Uploaded files (runtime)
├── exports/                  # Generated subtitle files (runtime)
├── requirements.txt
├── setup_env.sh              # Environment setup script
├── .env.example
├── docker-compose.yml        # PostgreSQL + Redis + App
├── Dockerfile
├── start.sh                  # Render / single-container entrypoint
└── README.md
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- FFmpeg (for audio extraction from video)
- PostgreSQL 14+ (included in Docker Compose)
- Redis (included in Docker Compose)

### 1. Clone & Setup

> **Recommended:** Use `setup_env.sh` to create the virtual environment, install dependencies, and verify imports:
>
> ```bash
> chmod +x setup_env.sh
> ./setup_env.sh
> ```
>
> Or manually:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | **Yes** | OpenAI API key (transcription + translation + analysis) |
| `DATABASE_URL` | **Yes** | PostgreSQL URL, e.g. `postgresql://termsub:termsub@db:5432/termsub` |
| `REDIS_URL` | **Yes** | Redis URL, e.g. `redis://redis:6379/0` |
| `UPLOAD_DIR` | No | Upload folder (default: `uploads`) |
| `EXPORT_DIR` | No | Export folder (default: `exports`) |

### 3. Database Migrations

TermSub uses Alembic as the single source of truth for schema changes. Apply migrations before starting the app:

```bash
alembic upgrade head
```

### 4. Run

#### Option A: Docker (Recommended)

```bash
docker compose up --build
```

Both the web and worker containers run `alembic upgrade head` automatically before starting.

#### Option B: Local Development

You need **PostgreSQL** and **Redis** running locally. Then start the Celery worker in one terminal:

```bash
source venv/bin/activate
alembic upgrade head
celery -A app.core.celery_app worker --loglevel=info --concurrency=2
```

And the FastAPI app in another:

```bash
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your browser, or use the deployed app at **https://www.termsub.eedbee.app**.

### API Docs

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/videos/upload` | POST | Upload file. Requires `target_language`. Max **500 MB**. |
| `/videos/{id}/transcribe` | POST | Queue transcription job. |
| `/videos/{id}/analyze` | POST | Queue Director + Glossary analysis. |
| `/videos/{id}/translate` | POST | Queue Translator agent. |
| `/videos/{id}/translate-direct` | POST | Set `skip_glossary=True` and queue translation. |
| `/videos/{id}/segments/add` | POST | Insert new segment, shifts subsequent up by 1. |
| `/videos/{id}/segments/{seg_id}/split` | POST | Split segment at time midpoint + nearest text boundary. |
| `/videos/{id}/segments/{seg_id}` | DELETE | Delete segment and shift subsequent down by 1. |
| `/videos/{id}/segments/{seg_id}` | PATCH | Update `translated_text` for a segment. |
| `/videos/{id}/replace` | POST | Global find & replace across all translated segments. |
| `/export/{id}/{format}` | GET | Download subtitles (`srt`, `vtt`, `txt`, `json`). |
| `/export/{id}/transcription` | GET | Download original transcription as SRT. |
| `/ws/videos/{id}` | WS | WebSocket for real-time progress updates. |

---

## Database Models

| Model | Purpose |
|-------|---------|
| **Video** | Uploaded file, status, languages, style guide, context analysis, `skip_glossary` |
| **Segment** | Timed transcript chunk (`original_text` + `translated_text`) |
| **Term** | Extracted key term, its translation, and standardized version |
| **TermOccurrence** | Links a Term to specific Segment(s) where it appears |
| **TranslationVariant** | Tracks different translations found for the same term |
| **JobQueue** | Background job with heartbeat, timeout, retry tracking, and Celery task ID |
| **ProcessingLog** | Detailed per-step logs for debugging |

### Video Status Pipeline

```
UPLOADED → QUEUED → EXTRACTING_AUDIO → TRANSCRIBING → TRANSCRIBED
→ ANALYZING → CONTEXT_READY → GLOSSARY_EXTRACTING → TERMS_READY
→ TRANSLATING → COMPLETED
```

When `skip_glossary=True`, the pipeline skips `ANALYZING` through `TERMS_READY` and goes directly from `TRANSCRIBED` to `TRANSLATING`.

Errors land in `ERROR` status.

---

## Development

### Running Tests

```bash
pytest
```

### Code Quality

This project uses **Ruff** for linting/formatting and **MyPy** for strict static type checking. CI runs both on every push to `main`.

```bash
# Lint check
ruff check .

# Format check
ruff format --check .

# Type check
mypy app/ --config-file pyproject.toml
```

### Database Migrations

Generate a new migration after model changes:

```bash
alembic revision --autogenerate -m "describe your change"
```

Apply migrations:

```bash
alembic upgrade head
```

### Environment Sync

If dependencies change:

```bash
./setup_env.sh
```

---

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy 2.0 + PostgreSQL
- **AI/ML**: OpenAI (`openai`) — whisper-1 for transcription, GPT-4o for translation
- **Queue**: Celery + Redis background worker with WebSocket updates via Redis Pub/Sub
- **Frontend**: Built-in vanilla JS + Tailwind CSS (served from `main.py`)
- **Audio**: FFmpeg for extraction
- **Code Quality**: Ruff (linting/formatting) + MyPy (strict type checking)
- **Testing**: pytest
- **Migrations**: Alembic
- **Deployment**: Docker Compose (PostgreSQL + Redis + App) or Render via `start.sh`

---

## License

MIT
