# TermSub

> **AI-Powered Video Translation & Terminology Management**

TermSub is a FastAPI application that transcribes, translates, and manages terminology for video content. It features a **multi-agent translation pipeline**, **Gemini-only transcription with WhisperX timestamp alignment**, a **built-in web UI with light/dark theme toggle**, and **real-time progress tracking** — all designed to produce consistent, high-quality subtitles with standardized terminology.

Built with a focus on **Persian (Farsi)** and other RTL languages, but supports any language pair Gemini can handle.

---

## Features

### Gemini-Only Transcription with WhisperX Alignment
Audio is extracted via FFmpeg and transcribed by **Google Gemini Flash**. Coarse timestamps are then refined with **WhisperX** word-level alignment (CPU fallback) for maximum accuracy.

### Multi-Agent Translation Pipeline
Translation is performed by three specialized AI agents working in sequence:

1. **Director Agent** — Analyzes content context, tone, and domain to generate a style guide
2. **Glossary Agent** — Extracts key terms (names, places, technical terms) for consistent translation
3. **Translator Agent** — Performs sliding-window translation using the glossary and full-transcript context as constraints

### Skip Terminology Mode
After transcription, choose to **Review Terminology** (run Director + Glossary) or **Skip & Translate Directly** to bypass analysis and go straight to translation.

### Subtitle Review & Editing
After translation, review and refine subtitles directly in the browser:

- **Visual Timeline** — Card-based grid showing every segment with timecodes and sequence numbers
- **Inline Editing** — Click any subtitle card to edit; changes auto-save on blur
- **Global Find & Replace** — Batch-replace text across all segments instantly
- **Segment Manipulation** — Split, add, and remove cards directly in the timeline
- **Context Brief** — Displays the auto-detected main topic from the content analysis
- **Light / Dark Theme** — Toggle between slate-based light mode and cinematic dark mode

### Terminology Management
- **Auto-extracted terms** — Detected by the Glossary Agent during analysis
- **Standardization** — Set a canonical translation for any term to ensure consistency across all segments
- **Translation variant detection** — Tracks when the same term gets translated differently

### Built-In Web UI
A complete single-page interface served at `http://localhost:8000/` with:
- Drag-and-drop file upload (video, audio, or text)
- Source/target language selection
- Real-time activity log with WebSocket live updates and color-coded badges
- Term review table with inline editing
- **Subtitle review timeline** with editable cards, split/add/remove, and global find & replace
- Toast notifications for save/replace confirmations
- One-click export buttons
- Light / dark theme toggle with persistent preference

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
- **Auto-cleanup** — Original video and temp `.wav` files are deleted after job completion or error

---

## Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│   Upload    │────▶│  FFmpeg Audio   │────▶│  Gemini Flash       │
│  (Video)    │     │   Extraction    │     │  Transcription      │
└─────────────┘     └─────────────────┘     └─────────────────────┘
                                                     │
                              ┌──────────────────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │ WhisperX Align  │  (CPU fallback)
                     │  (refine timestamps)
                     └─────────────────┘
                              │
┌─────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────┐
│                    Multi-Agent Translation Pipeline               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │Director Agent│─▶│Glossary Agent│─▶│   Translator Agent   │  │
│  │Style Guide   │  │Term Extraction│  │Sliding-Window Translate│ │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Terminology Review  │  Subtitle Timeline (Edit / Find & Replace) │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Export (SRT / VTT / TXT / JSON)                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
├── app/
│   ├── api/                  # FastAPI routers
│   │   ├── videos.py         # Upload, transcribe, analyze, translate, segments
│   │   ├── terms.py          # Term CRUD
│   │   ├── export.py         # SRT/VTT/TXT/JSON export
│   │   └── progress.py       # Progress tracking + logs + WebSocket sender
│   ├── core/
│   │   ├── config.py         # Pydantic settings (.env)
│   │   └── sqlite_queue.py   # Background job worker
│   ├── db/
│   │   ├── base.py           # SQLAlchemy base
│   │   ├── session.py        # Engine + session factory
│   │   └── session_utils.py  # Session helpers
│   ├── models/
│   │   ├── video.py          # Video, Segment, Term, JobQueue, ProcessingLog
│   │   └── job_queue.py      # JobQueue, JobStatus, JobType
│   ├── schemas/              # Pydantic request/response models
│   ├── services/
│   │   ├── whisper_service.py      # FFmpeg + Gemini transcription
│   │   ├── transcription.py        # WhisperX alignment for hybrid pipeline
│   │   ├── gemini_service.py       # Gemini translation + validation
│   │   ├── translation_pipeline.py # Multi-agent pipeline orchestration
│   │   ├── context_analysis_service.py # Director + Glossary agents
│   │   ├── progress_service.py     # Progress tracking
│   │   ├── upload_service.py       # File upload handling
│   │   └── text_parser.py          # Text file ingestion
│   └── main.py               # FastAPI app + WebSocket + built-in UI
├── migrations/               # Database migration scripts
├── uploads/                  # Uploaded files (runtime)
├── exports/                  # Generated subtitle files (runtime)
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
| `GEMINI_API_KEY` | **Yes** | Google Gemini API key (transcription + translation + analysis) |
| `DATABASE_URL` | No | SQLite default: `sqlite:///./termsub.db` |
| `UPLOAD_DIR` | No | Upload folder (default: `uploads`) |
| `EXPORT_DIR` | No | Export folder (default: `exports`) |

### 3. Database Migrations

If you are running against an existing database that predates recent schema changes, apply migrations before starting the app:

```bash
# Add skip_glossary column (required for v1.5.0+)
python migrations/add_skip_glossary_column.py

# Add job_queue timeout/heartbeat fields
python migrations/apply_migration.py
```

### 4. Run

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
- Sends audio to Gemini Flash for structured JSON transcription
- Runs WhisperX alignment to refine timestamps
- Saves segments with timestamps to the database

```bash
POST /videos/{id}/transcribe
```

### 3. Choose Next Step
After transcription completes, the UI presents two options:
- **Review Terminology** → runs Director + Glossary analysis
- **Skip & Translate Directly** → bypasses analysis and queues translation immediately

### 4. Analyze (Multi-Agent)
Click **Review Terminology**. Two agents run:
- **Director Agent** generates a style guide (tone, formality, domain)
- **Glossary Agent** extracts key terms and proposes translations

```bash
POST /videos/{id}/analyze
```

### 5. Review Terms
The UI shows all extracted terms. You can:
- Edit the **standardized translation** inline to lock in consistency

### 6. Translate
Click **Translate**. The Translator Agent uses the glossary and full original transcript to consistently translate all segments with a sliding-window approach.

```bash
POST /videos/{id}/translate
```

### 7. Review & Edit Subtitles
Once translation completes, the **Subtitle Review Timeline** appears:
- Browse all segments in a visual card grid with timecodes
- Click any card to edit translated text inline — changes auto-save on blur
- Use the **Global Find & Replace** bar to batch-replace text across all segments
- **Split** a card into two at the time midpoint
- **Add** a new empty card below any existing card
- **Remove** a card to delete it and auto-renumber subsequent segments

### 8. Export
Download subtitles in your preferred format:
```bash
GET /export/{id}/srt
GET /export/{id}/vtt
GET /export/{id}/txt
GET /export/{id}/json
GET /export/{id}/transcription   # Original (untranslated) SRT
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/videos/upload` | POST | Upload file. Requires `target_language`. |
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
| **JobQueue** | Background job with heartbeat, timeout, and retry tracking |
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

### Database Migrations
If you need to apply migrations manually:
```bash
python migrations/add_skip_glossary_column.py
python migrations/apply_migration.py
```

### Environment Sync
If dependencies change:
```bash
./setup_env.sh
```

---

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy + SQLite
- **AI/ML**: Google Gemini (`google-genai`), WhisperX, PyTorch
- **Queue**: SQLite-backed background worker with WebSocket updates
- **Frontend**: Built-in vanilla JS + Tailwind CSS with light/dark mode (served from `main.py`)
- **Audio**: FFmpeg for extraction
- **Testing**: pytest

---

## License

MIT
