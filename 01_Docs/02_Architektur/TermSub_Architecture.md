# TermSub - System Architecture

> **Agent:** AG-002 Architekt  
> **Date:** 2026-04-01  
> **Status:** Draft  
> **Checkpoint:** CP-KONZEPT-ARCHITECTURE-20260401-0930

---

## 1. Overview

TermSub is a FastAPI application for video transcription and translation with intelligent terminology management.

### Core Value Proposition
- Upload local video files → Get translated SRT subtitles
- AI extracts and tracks key terminology
- User reviews and standardizes translations
- Export consistent, professional subtitles

---

## 2. System Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TERMSUB DATA FLOW                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────┐   │
│  │  Video   │───▶│    Upload    │───▶│   Video     │───▶│  Video   │   │
│  │  File    │    │    Endpoint  │    │   Storage   │    │  Record   │   │
│  └──────────┘    └──────────────┘    └─────────────┘    └──────────┘   │
│                                                              │          │
│                                                              ▼          │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────┐   │
│  │ Whisper  │◀───│  Transcribe  │◀───│    Video    │◀───│  Status  │   │
│  │  Local   │    │   Service    │    │   Processor │    │  Update  │   │
│  └────┬─────┘    └──────────────┘    └─────────────┘    └──────────┘   │
│       │                                                                 │
│       ▼                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────┐   │
│  │ Segments │───▶│    Gemini    │───▶│  Translated │───▶│   Term   │   │
│  │  (Raw)   │    │   Translate  │    │  Segments   │    │ Extract  │   │
│  └──────────┘    └──────────────┘    └─────────────┘    └────┬─────┘   │
│                                                              │          │
│       ┌──────────────────────────────────────────────────────┘          │
│       ▼                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────┐   │
│  │   Term   │───▶│   Web UI     │───▶│   User      │───▶│  Term    │   │
│  │  Pool    │    │  Review Page │    │  Review     │    │  Update  │   │
│  └──────────┘    └──────────────┘    └─────────────┘    └──────────┘   │
│                                                              │          │
│                                                              ▼          │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────┐                   │
│  │   SRT    │◀───│   Export     │◀───│  Consistent │                   │
│  │  File    │    │   Service    │    │  Terms      │                   │
│  └──────────┘    └──────────────┘    └─────────────┘                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Database Models

### Entity Relationship Diagram

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│     Video       │       │    Segment      │       │      Term       │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ id (PK)         │──┐    │ id (PK)         │    ┌──│ id (PK)         │
│ filename        │  │    │ video_id (FK)   │────┘  │ video_id (FK)   │
│ original_path   │  └───▶│ start_time      │       │ source_text     │
│ status          │       │ end_time        │       │ target_text     │
│ source_language │       │ source_text     │       │ occurrences     │
│ target_language │       │ target_text     │       │ is_standardized │
│ created_at      │       │ confidence      │       │ standardized_to │
│ updated_at      │       │ sequence        │       │ context         │
└─────────────────┘       └─────────────────┘       └─────────────────┘
         │                        │
         │                        │
         └────────────────────────┘
              One-to-Many
```

### Model Details

#### Video Model
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| filename | String | Original filename |
| original_path | String | Storage path |
| status | Enum | PENDING → TRANSCRIBING → TRANSLATING → REVIEW → COMPLETED |
| source_language | String | Auto-detected or user-specified |
| target_language | String | Target translation language |
| whisper_model | String | Whisper model used (base/small/medium/large) |
| created_at | DateTime | Upload timestamp |
| updated_at | DateTime | Last update timestamp |

#### Segment Model
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| video_id | FK | Reference to Video |
| sequence | Integer | Order in subtitle sequence |
| start_time | Float | Start time in seconds |
| end_time | Float | End time in seconds |
| source_text | Text | Original transcription |
| target_text | Text | Translated text |
| confidence | Float | Whisper confidence score |

#### Term Model
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| video_id | FK | Reference to Video |
| source_text | String | Term in source language |
| target_text | String | Proposed translation |
| occurrences | Integer | How many times it appears |
| is_standardized | Boolean | User confirmed? |
| standardized_to | FK | Self-reference for grouping |
| context | JSON | Example sentences/context |

---

## 4. Project Structure

```
termub/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI entry point
│   ├── config.py               # Settings & env vars
│   ├── database.py             # SQLAlchemy setup
│   ├── models/                 # Database models
│   │   ├── __init__.py
│   │   ├── video.py
│   │   ├── segment.py
│   │   └── term.py
│   ├── routers/                # API endpoints
│   │   ├── __init__.py
│   │   ├── upload.py           # Video upload
│   │   ├── video.py            # Video CRUD
│   │   ├── segment.py          # Segment operations
│   │   ├── term.py             # Term management
│   │   └── export.py           # SRT export
│   ├── services/               # Business logic
│   │   ├── __init__.py
│   │   ├── whisper_service.py  # Local transcription
│   │   ├── gemini_service.py   # Translation & term extraction
│   │   ├── video_processor.py  # Video handling
│   │   └── srt_generator.py    # SRT file creation
│   ├── static/                 # CSS, JS
│   │   ├── css/
│   │   └── js/
│   └── templates/              # HTML templates
│       ├── base.html
│       ├── upload.html
│       ├── review.html
│       └── download.html
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_upload.py
│   ├── test_transcribe.py
│   └── test_translate.py
├── docs/
│   └── api.md
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 5. API Endpoints

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/upload` | Upload video file |
| GET | `/api/v1/videos` | List all videos |
| GET | `/api/v1/videos/{id}` | Get video details |
| GET | `/api/v1/videos/{id}/segments` | Get all segments |
| GET | `/api/v1/videos/{id}/terms` | Get extracted terms |
| PUT | `/api/v1/terms/{id}` | Update term translation |
| POST | `/api/v1/terms/{id}/standardize` | Set as standard |
| GET | `/api/v1/videos/{id}/export/srt` | Download SRT file |

### Web UI Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Upload page |
| GET | `/review/{video_id}` | Term review UI |
| GET | `/download/{video_id}` | Download page |

---

## 6. External Services

### Google Gemini API
- **Usage**: Translation + Term extraction
- **Model**: gemini-2.0-flash (fast) or gemini-2.0-pro (accurate)
- **API Key**: From environment `GEMINI_API_KEY`

### OpenAI Whisper (Local)
- **Usage**: Audio transcription
- **Models**: base (fast) → large-v3 (accurate)
- **Local execution**: No API key needed

---

## 7. Technology Stack

| Layer | Technology |
|-------|------------|
| Framework | FastAPI |
| Database | SQLite (dev) / PostgreSQL (prod) |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Templates | Jinja2 |
| Styling | TailwindCSS (CDN) |
| Transcription | OpenAI Whisper (local) |
| Translation | Google Gemini API |
| Testing | pytest |

---

## 8. Configuration

### Environment Variables

```bash
# API Keys
GEMINI_API_KEY=your_gemini_api_key_here

# App Settings
APP_NAME=TermSub
DEBUG=true
UPLOAD_DIR=./03_Data/uploads
MAX_FILE_SIZE=500MB

# Whisper Settings
WHISPER_MODEL=base  # base, small, medium, large-v1/v2/v3
WHISPER_DEVICE=auto  # cpu, cuda, auto

# Database
DATABASE_URL=sqlite:///./03_Data/termub.db

# Gemini
GEMINI_MODEL=gemini-2.0-flash
TARGET_LANGUAGE=de  # default target language
```

---

## 9. Flow Details

### Step 1: Upload
1. User uploads video via web UI
2. File saved to `03_Data/uploads/{video_id}/`
3. Video record created with status PENDING
4. Background task triggered for processing

### Step 2: Transcription (Whisper)
1. Extract audio from video (if needed)
2. Run Whisper locally
3. Create Segment records for each transcription
4. Update Video status to TRANSCRIBING → TRANSLATING

### Step 3: Translation (Gemini)
1. Send segments to Gemini API
2. Get translated text
3. Update Segment records with translations
4. Extract terms using Gemini prompt engineering

### Step 4: Term Extraction (Gemini)
Prompt template:
```
Analyze these translation segments and extract key terminology:

Segments: {segments_json}

Identify:
1. Technical terms
2. Proper nouns
3. Domain-specific vocabulary
4. Repeated phrases that should be consistent

Return JSON format:
{
  "terms": [
    {
      "source": "original term",
      "target": "translation",
      "occurrences": [segment_ids],
      "category": "technical/proper_noun/domain"
    }
  ]
}
```

### Step 5: Review UI
- Show all extracted terms grouped by similarity
- Highlight inconsistencies
- Allow user to edit and standardize
- Auto-update related segments

### Step 6: Export
- Generate SRT with standardized terms
- Timestamps from Whisper segments
- Download or preview

---

## 10. Next Steps

1. ✅ Architecture defined (AG-002)
2. ⏳ Database models implementation (AG-005)
3. ⏳ API endpoints (AG-005)
4. ⏳ Whisper integration (AG-005)
5. ⏳ Gemini integration (AG-005)
6. ⏳ Web UI (AG-005)
7. ⏳ Testing (AG-007)

---

*Architecture by AG-002 Architekt*  
*Next Agent: AG-005 Developer for implementation*
