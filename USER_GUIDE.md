# TermSub User Guide

Your complete workflow companion for AI-powered video translation, terminology management, and subtitle production.

---

## Getting Started

For setup instructions, see [README.md](README.md). You have two options:

- **Docker** — `docker compose up --build` (includes PostgreSQL, Redis, and Celery worker)
- **Local** — Python 3.11+ virtual environment with Redis running locally

You can also use the deployed app at **https://www.termsub.eedbee.app/app**.

Once the app is running, open **`http://localhost:8000/app`** in your browser and follow the workflow below.

---

## How to use TermSub

| Step | Action | Outcome |
|------|--------|---------|
| **1. Upload** | Select a video, audio, or text file and choose source/target languages. | File queued for processing. |
| **2. Review extracted terms** | TermSub identifies names, brands, and technical terms. Edit them to lock in consistency. | A glossary that controls the rest of the translation. |
| **3. Translate & edit subtitles** | Get context-aware translations in 59 languages, then edit timing and text of subtitles. | Polished, publication-ready subtitles. |
| **4. Export** | Click **SRT**, **VTT**, **TXT**, or **JSON**. | Production file ready for NLE or delivery. |

---

## The Core Workflow: From Upload to Export

The TermSub workflow follows a clear, linear path. Each stage builds on the last, giving you full control over quality at every step.

### 1. Upload a video, audio or text file

- Click the **drop zone** to select a file from your computer.
- TermSub accepts:
  - **Video files**: MP4, MOV, AVI
  - **Audio files**: MP3, WAV, M4A
  - **Text files**: `.txt` or `.srt` (use this if you already have a transcript and want to skip transcription)
- Choose your **source language** and **target language**. TermSub supports **59 languages** and puts the most common ones at the top of the dropdown.

> **Note:** Maximum upload size is **500 MB per file**.

> **Tip:** If you upload a `.txt` or `.srt` file, TermSub will skip the audio transcription phase and move directly to analysis and translation.

### 2. Review extracted terms

This is the step other tools skip — and it is what makes TermSub accurate.

TermSub scans your transcript for key terminology: proper nouns, technical concepts, recurring phrases, and culturally specific expressions. The **Extracted Terms** panel shows:

- **Type** (e.g., Key Concept, Proper Noun)
- **Original** term
- **Translation** proposed by the AI
- **Standard** — an editable field for your preferred translation

**How to manage your glossary:**

- **Edit the Standard column** to lock in your preferred translation for the entire project.
- **Match established translations** for book titles, branded terms, famous quotes, etc.
- **Unify inconsistencies** if the same concept appears with multiple translations.
- **Verify domain accuracy** for scientific or technical terms.

> **Tip:** Do not skip this step. Refining your glossary now saves hours of manual correction later, especially on projects with dense terminology.

#### Skip Glossary (Fast Track)

If terminology consistency is less critical for your project, click **Skip & Translate Directly** after transcription. TermSub will move straight to the translation phase without extracting or displaying the glossary.

### 3. Translate & edit subtitles

Click **Translate Subtitles**. The Translator Agent processes your transcript segment by segment, using a sliding-window approach that ensures each subtitle is translated with awareness of the surrounding context. Your glossary acts as a hard constraint: every standardized term is translated exactly as you specified.

When translation finishes, the **Subtitle Timeline** appears. Each card shows:

- **Sequence number** (e.g., `#12`)
- **Timecode** (e.g., `⏱ [01:23.450 → 01:27.120]`)
- **Translated text** (editable inline)

**Editing tools:**

- **Inline editing** — Click any subtitle text to edit. Changes auto-save on blur.
- **Split** — Divide a long segment at a natural break point.
- **Add** — Insert a new blank segment below any card.
- **Remove** — Delete a card; sequence numbers renumber automatically.
- **Global Find & Replace** — Batch-replace text across the entire timeline.

> **Tip:** The editor preserves RTL direction automatically for Persian, Arabic, and Hebrew.

### 4. Export

When you are satisfied with your subtitles, download them in your preferred format:

| Format | Best For |
|--------|----------|
| **SRT** | Universal subtitle format. Compatible with virtually every NLE and media player. |
| **WebVTT** | Web streaming, HTML5 video players, and online platforms. |
| **TXT** | Plain-text transcript for scripts, captions, or archival use. |
| **JSON** | Structured data export for custom pipelines or third-party tools. |

#### RTL Punctuation Fixes (Automatic)

If your target language is Persian, Arabic, or any other RTL language, TermSub **automatically applies punctuation fixes** during SRT export so final punctuation appears on the correct side of the line and mixed LTR/RTL text renders cleanly.

#### Using Your Exported Files

- **VLC playback** — Drag and drop the `.srt` file onto the VLC window while your original video plays.
- **Adobe Premiere Pro** — Import the `.srt` and drag it onto a video track above your footage.
- **DaVinci Resolve** — Import the `.srt` or `.vtt` in the Edit page; subtitles land on a dedicated subtitle track.
- **Web & streaming** — Upload the `.vtt` alongside your video asset and reference it in a `<track>` element.

---

## Tips for Best Results

- **Upload clean audio** — The clearer your source audio, the more accurate the initial transcription.
- **Refine the glossary before translating** — A two-minute glossary review prevents hours of timeline correction.
- **Use Find & Replace before manual edits** — Fix systemic translation issues globally first, then fine-tune individual cards.
- **Export SRT for maximum compatibility** — SRT is the safest choice when you are unsure what your editor or platform expects.
- **Keep your API key handy** — For BYOK mode, the key is stored in your browser; clearing site data will remove it.

---

*TermSub — Seamless translation. Consistent terminology. Production-ready subtitles.*
