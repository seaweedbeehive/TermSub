# TermSub

> **AI-Powered Video Translation & Terminology Management**

TermSub is a FastAPI application that transcribes, translates, and manages terminology for video content. It features a **multi-agent translation pipeline**, **three transcription providers**, a **built-in web UI**, and **real-time WebSocket progress tracking** — all designed to produce consistent, high-quality subtitles with standardized terminology.

Built with a focus on **Persian (Farsi)** and other RTL languages, but supports any language pair Gemini can handle.

---

## Features

### Multi-Provider Transcription
Choose the transcription engine that fits your needs:

| Provider | Speed | Privacy | Best For |
|----------|-------|---------|----------|
| **Groq (Whisper)** | ⚡ Fastest | ☁️ Cloud | Quick turnaround, high accuracy |
| **Gemini Flash** | 🚀 Fast | ☁️ Cloud | Structured JSON output, Google ecosystem |
| **Local (faster-whisper)** | 🐢 CPU-bound | 🔒 Offline | Privacy-sensitive content, no API keys |

### Multi-Agent Translation Pipeline
Translation is performed by three specialized AI agents working in sequence:

1. **Director Agent** — Analyzes content context, tone, and domain to generate a style guide
2. **Glossary Agent** — Extracts key terms (names, places, technical terms) for consistent translation
3. **Translator Agent** — Performs sliding-window translation using the glossary as constraints

### Terminology Management
- **Auto-extracted terms** — Detected by the Glossary Agent during analysis
- **Custom terms** — Manual find-and-replace entries you can add via the UI
- **Standardization** — Set a canonical translation for any term to ensure consistency across all segments
- **Translation variant detection** — Tracks when the same term gets translated differently

### Built-In Web UI
A complete single-page interface served at `http://localhost:8000/` with:
- Drag-and-drop file upload (video, audio, or text)
- Source/target language selection
- Transcription engine picker
- Real-time progress bar with step details
- Term review table with inline editing
- Activity log with WebSocket live updates
- One-click export buttons

### Export Formats
- **SRT** — SubRip subtitles with RTL punctuation fixes
- **WebVTT** — HTML5 video subtitles
- **TXT** — Plain translated text
- **JSON** — Full metadata + all segments
- **Original Transcription SRT** — Pre-translation subtitles

### Additional Features
- **Text file bypass** — Upload `.txt` or `.srt` to skip transcription entirely
- **WebSocket progress** — Real-time status updates during long-running jobs
- **Background job queue** — SQLite-based worker with heartbeat, timeout recovery, and retry logic
- **Processing logs** — Detailed per-step logging for debugging
- **CORS enabled** — Ready for frontend integration

---

## Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│   Upload    │────▶│  FFmpeg Audio   │────▶│  Transcription      │
│  (Video)    │     │   Extraction    │     │  (Groq/Gemini/Local)│
└─────────────┘     └─────────────────┘     └─────────────────────┘
                                                     │
┌────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────┐
│                    Multi-Agent Translation Pipeline               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │Director Agent│─▶│Glossary Agent│─▶│   Translator Agent   │  │
│  │Style Guide   │  │Term Extraction│  │Sliding-Window Translate│  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Terminology Review  │  Custom Terms  │  Export (SRT/VTT/TXT/JSON) │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
├── app/
│   ├── api/                  # FastAPI routers
│   │   ├── videos.py         # Upload, transcribe, analyze, translate
│   │   ├── terms.py          # Term CRUD + custom terms
│   │   ├── export.py         # SRT/VTT/TXT/JSON export
│   │   └── progress.py       # Progress tracking + logs
│   ├── core/
│   │   ├── config.py         # Pydantic settings (.env)
│   │   └── sqlite_queue.py   # Background job worker
│   ├── db/
│   │   ├── base.py           # SQLAlchemy base
│   │   ├── session.py        # Engine + session factory
│   │   └── session_utils.py  # Session helpers
│   ├── models/
│   │   └── video.py          # Video, Segment, Term, JobQueue, ProcessingLog
│   ├── schemas/              # Pydantic request/response models
│   ├── services/
│   │   ├── whisper_service.py    # Transcription (Groq/Gemini/Local)
│   │   ├── gemini_service.py     # Gemini translation + validation
│   │   ├── translation_pipeline.py # Multi-agent pipeline
│   │   ├── context_analysis_service.py # Director + Glossary agents
│   │   ├── progress_service.py   # Progress tracking
│   │   ├── upload_service.py     # File upload handling
│   │   └── text_parser.py        # Text file ingestion
│   └── main.py               # FastAPI app + WebSocket + built-in UI
├── migrations/               # Database migration scripts
├── uploads/                  # Uploaded files
├── exports/                  # Generated subtitle files
├── requirements.txt
├── setup_env.sh              # Environment setup script
├── .env.example
└── README.md
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- FFmpeg (for audio extraction from video)

### 1. Clone & Setup

> **Recommended:** Use `setup_env.sh` to automatically create the virtual environment, install dependencies, and verify all imports:
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
| `GEMINI_API_KEY` | **Yes** | Google Gemini API key (translation + analysis) |
| `GROQ_API_KEY` | No* | Groq API key (fastest transcription) |
| `OPENAI_API_KEY` | No | Reserved for future use |
| `TRANSCRIPTION_PROVIDER` | No | `groq` (default), `gemini`, or `local` |
| `DATABASE_URL` | No | SQLite default: `sqlite:///./termsub.db` |
| `UPLOAD_DIR` | No | Upload folder (default: `uploads`) |
| `EXPORT_DIR` | No | Export folder (default: `exports`) |
| `LOCAL_WHISPER_DEVICE` | No | `cpu` or `cuda` (default: `cpu`) |
| `LOCAL_WHISPER_COMPUTE_TYPE` | No | `int8`, `float16`, etc. (default: `int8`) |

\* Required only if using Groq transcription.

### 3. Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your browser.

### API Docs
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## How It Works

### 1. Upload
Upload a video, audio, or text file via the web UI or API:
```bash
POST /videos/upload
```

### 2. Transcribe
Click **Transcribe** (or call the API). The background worker:
- Extracts audio with FFmpeg (16kHz mono WAV)
- Sends audio to your chosen transcription provider
- Saves segments with timestamps to the database

```bash
POST /videos/{id}/transcribe?provider=groq
```

### 3. Analyze (Multi-Agent)
Click **Analyze Content**. Two agents run:
- **Director Agent** generates a style guide (tone, formality, domain)
- **Glossary Agent** extracts key terms and proposes translations

```bash
POST /videos/{id}/analyze
```

### 4. Review Terms
The UI shows all extracted terms. You can:
- Edit the **standardized translation** inline
- Add **custom terms** (manual find-and-replace)
- Delete custom terms

### 5. Translate
Click **Translate**. The Translator Agent uses the glossary to consistently translate all segments with a sliding-window approach.

```bash
POST /videos/{id}/translate
```

### 6. Export
Download subtitles in your preferred format:
```bash
GET /export/{id}/srt
GET /export/{id}/vtt
GET /export/{id}/txt
GET /export/{id}/json
GET /export/{id}/transcription   # Original (untranslated) SRT
```

---

## Transcription Providers

### Groq (Default)
Fastest option. Uses Groq's hosted Whisper API via the OpenAI-compatible client.
```env
TRANSCRIPTION_PROVIDER=groq
GROQ_WHISPER_MODEL=whisper-large-v3
```

### Gemini Flash
Returns structured JSON with segment timestamps. Good for Google ecosystem users.
```env
TRANSCRIPTION_PROVIDER=gemini
```

### Local (faster-whisper)
Offline, privacy-first. Runs on CPU (or CUDA if configured). Model downloaded on first run.
```env
TRANSCRIPTION_PROVIDER=local
LOCAL_WHISPER_MODEL=large-v3
LOCAL_WHISPER_DEVICE=cpu
LOCAL_WHISPER_COMPUTE_TYPE=int8
```

You can also override the provider per-request via the UI dropdown or API:
```bash
POST /videos/{id}/transcribe?provider=gemini
```

---

## Database Models

| Model | Purpose |
|-------|---------|
| **Video** | Uploaded file, status, languages, style guide, context analysis |
| **Segment** | Timed transcript chunk (`original_text` + `translated_text`) |
| **Term** | Extracted key term, its translation, and standardized version |
| **TermOccurrence** | Links a Term to specific Segment(s) where it appears |
| **TranslationVariant** | Tracks different translations found for the same term |
| **JobQueue** | Background job with heartbeat, timeout, and retry tracking |
| **ProcessingLog** | Detailed per-step logs for debugging |

---

## Development

### Running Tests
```bash
pytest
```

### Database Migrations
If you need to apply migrations manually:
```bash
python migrations/apply_migration.py
```

### Checking Available Gemini Models
```bash
python check_models.py
```

### Environment Sync
If dependencies change:
```bash
./setup_env.sh
```

---

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy + SQLite
- **AI/ML**: Google Gemini (`google-genai`), Groq Whisper, faster-whisper
- **Queue**: SQLite-backed background worker with WebSocket updates
- **Frontend**: Built-in vanilla JS + Tailwind CSS (served from `main.py`)
- **Audio**: FFmpeg for extraction

---

## License

MIT
