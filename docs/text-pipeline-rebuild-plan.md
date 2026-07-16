# Text Pipeline Rebuild Plan

## Problem Statement

The current `feat/text-pipeline` branch tries to force text files through the existing video translation machinery. This causes several bugs:

- Text translations return the original language instead of the target language.
- There is no extracted-terminology step for text files.
- The UI shows a video-oriented preview (top/bottom timeline) instead of a text-oriented side-by-side editor.
- Source language `auto` leaks into prompts, confusing the model.
- Subtitle broadcast constraints (42 chars/line, 2 lines max) are applied to plain text.

The goal is to build a **completely separate text pipeline** that mirrors the high-level video flow (upload → extract terms → review terms → translate → edit/download) but does **not modify any code used by the video pipeline**.

---

## Desired User Flow

1. User selects a `.txt` file.
2. Main buttons change:
   - **Translate Text** (was "Translate and Get Subtitles")
   - Hide **Get Subtitles in Original Language**.
3. User chooses source and target languages.
4. User clicks **Translate Text**.
5. Backend parses file into `Segment` rows (`content_type="text"`, no timestamps).
6. Backend extracts terminology (Pass 1: context analysis, Pass 2: glossary extraction).
7. Frontend shows extracted terms for review/edit.
8. User clicks **Translate**.
9. Backend translates all segments using the reviewed glossary.
10. Frontend shows a **side-by-side** editor: original on the left, translated on the right, editable.
11. User downloads the translated text as `.txt`.

---

## Architecture Principle

**Do not touch video code.** Create parallel files for text. Only reuse read-only building blocks (models, DB session helpers, OpenAI client, progress tracker, quota manager).

---

## New Backend Files

### 1. `app/api/text_translation.py` (new router)

Mount under `/api/text`.

Endpoints:

- `POST /text/{video_id}/extract-terms`
  - Runs context analysis + glossary extraction for the text record.
  - Allowed when status is `transcribed`.
  - Returns `{"job_id": ...}` so the frontend can track progress via WebSocket or polling.

- `POST /text/{video_id}/translate`
  - Translates all segments using the existing `Term` rows for this record.
  - Allowed when status is `terms_ready`.
  - Enforces text-translation character quota for non-BYOK users.
  - Returns `{"job_id": ...}`.

- `GET /text/{video_id}/segments`
  - Returns all segments with `original_text` and `translated_text`.
  - Used by the side-by-side editor.

- `GET /text/{video_id}/terms`
  - Returns extracted terms for the review panel.

- `POST /text/{video_id}/export`
  - Joins `translated_text` values in sequence order and returns a `.txt` file download.

- `PATCH /text/{video_id}/segments/{segment_id}`
  - Allows editing `translated_text` in the side-by-side view.

- `PATCH /text/terms/{term_id}`
  - Allows editing extracted terms (or reuse existing `PATCH /terms/{term_id}` if it works for text records too).

### 2. `app/services/text_translation_service.py` (new service)

Orchestrator with three public functions:

- `extract_terms_for_text(video_id: str) -> dict[str, Any]`
  - Loads text record and segments.
  - Calls context analysis agent.
  - Saves context analysis JSON to `video.context_analysis`.
  - Calls glossary extraction agent.
  - Saves terms to `Term` table with `source=AUTO`.
  - Updates status to `terms_ready`.

- `translate_text(video_id: str) -> dict[str, Any]`
  - Loads record, segments, and terms.
  - Checks quota.
  - Calls text translator agent to fill `Segment.translated_text`.
  - Records quota consumption.
  - Updates status to `completed`.

- `export_text_translation(video_id: str) -> str`
  - Joins `translated_text` with double newlines and returns the raw string.

All functions use short-lived DB sessions (ZERO-LEAK policy consistent with existing code).

### 3. `app/agents/text_context_agent.py` (new agent)

Copy the prompt structure from `app/services/context_analysis_service.py`:

- Pass 1: analyze context and extract key terms.
- Pass 2: extract standardized glossary and named entities.

Differences for text:

- Prompt explicitly says the input is a plain text document, not a video transcript.
- Source language handling: if `source_language` is `auto` or missing, ask the model to detect it and return `detected_source_language`.
- Store detected language back on the `Video` record.

### 4. `app/agents/text_translator_agent.py` (new agent)

Copy batching/retry logic from `app/agents/translator.py` but with these changes:

- Prompt is plain-text focused (no subtitle constraints, no "timeline segments").
- Input: list of segments with `sequence_number` and `original_text`.
- Output: JSON with `translations` array, each with `sequence_number` and `translated_text`.
- Uses glossary from `Term` table.
- Handles `source_language == "auto"` by omitting it from the prompt.
- Model name should be configurable; default to a real OpenAI model such as `gpt-4o-mini`, not `gpt-5.4-mini`.

### 5. `app/worker/text_tasks.py` (new Celery tasks)

- `extract_text_terms_task(video_id: str)`
  - Calls `text_translation_service.extract_terms_for_text`.
- `translate_text_task(video_id: str)`
  - Calls `text_translation_service.translate_text`.

These tasks are separate from `app/worker/tasks.py` video tasks.

---

## New Frontend Files

### 6. `frontend/js/textPipeline.js` (new module)

Self-contained module exposing:

- `initTextPipeline()` — call once on page load.
- `handleTextFileSelected(file)` — when `.txt` is chosen.
- `startTextExtraction()` — call `POST /api/text/{id}/extract-terms`.
- `renderTextTerms(terms)` — show terms panel.
- `updateTextTerm(termId, value)` — PATCH term.
- `startTextTranslation()` — call `POST /api/text/{id}/translate`.
- `renderSideBySide(segments)` — show left/right editor.
- `updateTextSegment(segmentId, value)` — PATCH segment.
- `downloadTextTranslation()` — call `POST /api/text/{id}/export` and trigger download.

### 7. `frontend/index.html` additions

Add hidden containers (do not remove video containers):

- `#textTermsPanel` — terms review for text.
- `#textSideBySideEditor` — left/right editor.
- `#textDownloadPanel` — download button for text.

### 8. Minimal changes to `frontend/js/main.js`

- When `currentFileType === 'text'`, route button clicks to `textPipeline.js` instead of the video functions.
- Keep all video logic untouched.
- Load text terms/side-by-side containers from the HTML.

---

## Data Model Notes

Reuse existing models without schema changes:

- `Video` record with `content_type="text"` already exists.
- `Segment` rows already store `original_text` and `translated_text`.
- `Term` rows already link to `video_id`.

Only addition: `video.context_analysis` JSON is already a column; use it for text too.

---

## Quota

Text translation should consume the text-page quota implemented in `app/core/quota.py`:

- 100 pages × 3,000 characters per page.
- Check before translating.
- Record consumption after successful translation.
- BYOK users bypass the quota.

---

## WebSocket / Progress

Option A: Use existing WebSocket progress infrastructure. The new Celery tasks can call `progress_tracker.update_progress` and emit the same events the frontend already understands (`transcribed`, `terms_ready`, `translating`, `completed`).

Option B: Use HTTP polling only for text. Simpler and avoids touching WebSocket auth, but less consistent UX.

Recommendation: **Option A** for consistency, but make the text pipeline gracefully fall back to polling if WebSocket is not connected.

---

## What NOT to Touch

These files should remain unchanged:

- `app/services/translation_pipeline.py`
- `app/services/gemini_service.py`
- `app/agents/translator.py`
- `app/worker/tasks.py`
- `app/api/videos.py` (video endpoints)
- Video-specific frontend flow in `frontend/js/main.js` (only add branching)
- Video UI containers in `frontend/index.html`

---

## Open Questions

1. Should terminology extraction for text be synchronous or async (Celery)?
   - Recommendation: async so large documents don't block the web server.

2. Should the side-by-side editor save edits automatically or require a Save button?
   - Recommendation: debounced auto-save (PATCH on blur/after typing pause).

3. Should text records appear in "My Jobs"?
   - Recommendation: yes, since they use the same `Video` table.

4. Should the text pipeline support `skip_glossary` (the terminology checkbox)?
   - Recommendation: yes, but default to extracting terms. If unchecked, skip to direct translation.

5. What is the correct OpenAI model name to use?
   - The codebase references `gpt-5.4-mini`, which is not a real OpenAI model. The new text pipeline should default to `gpt-4o-mini` or read from an environment variable.

---

## Suggested Implementation Order

1. Create `app/agents/text_context_agent.py` and `app/agents/text_translator_agent.py`.
2. Create `app/services/text_translation_service.py`.
3. Create `app/worker/text_tasks.py`.
4. Create `app/api/text_translation.py` and mount it in `app/main.py`.
5. Add HTML containers in `frontend/index.html`.
6. Create `frontend/js/textPipeline.js`.
7. Add text-file branching in `frontend/js/main.js`.
8. Test end-to-end with a small `.txt` file.
9. Run existing video tests to ensure no regression.

---

## Files to Create

```
app/
  api/
    text_translation.py
  agents/
    text_context_agent.py
    text_translator_agent.py
  services/
    text_translation_service.py
  worker/
    text_tasks.py
frontend/
  js/
    textPipeline.js
docs/
  text-pipeline-rebuild-plan.md
```

## Files to Modify Minimally

```
app/main.py            # mount /api/text router
frontend/index.html    # add text containers
frontend/js/main.js    # branch text files to textPipeline.js
```
