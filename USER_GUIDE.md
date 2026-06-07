# TermSub User Guide

**Your complete workflow companion for AI-powered video translation, terminology management, and subtitle production.**

---

## What is TermSub?

**TermSub** is a web-based translation and subtitle management system designed for anyone who needs high-quality, precise video translation. While it is built to handle the rigorous demands of video editors, documentary filmmakers, and journalists, it is equally valuable for professionals across any field.

Whether you are translating a scientific interview, a technical documentary, a political analysis, or a psychological breakdown, TermSub ensures that your terminology remains **consistent**, **contextually accurate**, and **production-ready** from the first upload to the final export.

Instead of juggling separate tools for transcription, translation, and glossary management, TermSub combines everything into a single, streamlined pipeline. You upload your media, review the AI-extracted glossary, refine the translation in a visual timeline, and export clean subtitle files ready for delivery or post-production.


---

## Workflow Summary

| Step | Action | Outcome |
|------|--------|---------|
| **Upload** | Select video, audio, or text file. | File queued for processing. |
| **Configure** | Set source/target language and API key. | Pipeline knows your requirements. |
| **Transcribe** | Click **Start**, then **Transcribe Audio** (or **Parse Text**). | Accurate transcript with word-level timing. |
| **Analyze** | Review glossary. Standardize terms. | Locked-in terminology for consistent translation. |
| **Translate** | Click **Translate Subtitles**. | Full translated subtitle timeline. |
| **Refine** | Edit inline, split, add, remove, or find & replace. | Polished, publication-ready subtitles. |
| **Export** | Click **SRT**, **VTT**, **TXT**, or **JSON**. | Production file ready for NLE or delivery. |


---

## The Core Workflow: From Upload to Export

The TermSub workflow follows a clear, linear path. Each stage builds on the last, giving you full control over quality at every step.

### 1. Upload Your Media

Begin by opening the TermSub web interface in your browser.

- Click the **drop zone** (or the upload area) to select a file from your computer.
- TermSub accepts:
  - **Video files**: MP4, MOV, AVI
  - **Audio files**: MP3, WAV, M4A
  - **Text files**: `.txt` or `.srt` (use this if you already have a transcript and want to skip transcription)
- Once selected, your filename appears in the upload area.

> **Tip:** If you upload a `.txt` or `.srt` file, TermSub will skip the audio transcription phase and move directly to analysis and translation.

### 2. Configure Your Language Pair

Before starting, tell TermSub which languages you are working with:

- **Source Language**: Choose the language spoken in your video, or select **Auto-detect** to let the AI identify it automatically.
- **Target Language**: Select the language you want your subtitles translated into.

> **Tip:** TermSub is built with particular strength for **Persian (Farsi)**, **Arabic**, and other **right-to-left (RTL)** languages, including automatic punctuation fixes during export.

### 3. Enter Your OpenAI API Key

In the **OpenAI API Key** field, paste your personal API key from the OpenAI Platform.

- This key powers the AI transcription, analysis, and translation engines.
- Your key is saved locally in your browser for convenience and is never stored on the server.
- If you need a key, click **Get an API key at OpenAI Platform** beneath the input field for a guided walkthrough.

### 4. Start the Pipeline

Click the **Start** button. TermSub immediately uploads your file and queues it for processing.

The **Activity Log** shows a real-time stream of every step, so you always know exactly what is happening.

---

**Note for the Nerds**: In the following stages, the "What Happens" sections explain the technical AI pipeline working behind the scenes. If you just want to get your subtitles done, feel free to skip to the "What You See" and instruction steps!

---

## Stage 1: Transcription

If you uploaded video or audio, TermSub begins by extracting a precise transcript.

### What Happens

1. **Audio Extraction**: The audio track is extracted from your video file using FFmpeg.
2. **Cloud Transcription**: The audio is sent to **OpenAI whisper-1**, which returns a structured transcript with segment-level timestamps born directly from the cloud.
3. **No Local Alignment Needed**: Because text and timestamps are generated together by the cloud model, no secondary alignment step is required.

### What You See

- The **Status Card** updates to show the current step.
- The **Segment Counter** displays how many subtitle segments have been identified.
- When transcription is complete, the status changes to **Transcribed** and a new primary action button appears.

---

## Stage 2: Multi-Agent Analysis (The Director & Glossary Agents)

This is where TermSub distinguishes itself from ordinary translation tools.

### The Director Agent

The **Director Agent** analyzes your transcript for:

- **Domain**: Is this a medical lecture? A legal deposition? A technical tutorial?
- **Tone**: Formal, conversational, dramatic, instructional?
- **Style context**: Audience level, cultural references, and register.

This context brief is displayed in your **Status Card** as the *Director's Context Brief*, ensuring every downstream decision is grounded in the actual nature of your content.

### The Glossary Agent

The **Glossary Agent** scans the transcript for key terminology—proper nouns, technical concepts, recurring phrases, and culturally specific expressions—and extracts them into a structured glossary.

### What You See

- The **Extracted Terms** panel populates with a table showing:
  - **Type** (e.g., Key Concept, Proper Noun)
  - **Original** term
  - **Translation** proposed by the AI
  - **Standard** (an editable field for your preferred translation)

### How to Manage Your Glossary

**This is one of the most important features of the entire application**. Your glossary acts as a hard rulebook for the AI, ensuring perfect consistency across your entire video. Take a moment to review each term:

- **Edit the Standard column**: Click into the text field next to any term and type your preferred translation. This overrides the AI suggestion for the entire project.
- **Match established translations**: If a specific book, movie title, branded term, or famous quote is mentioned, and an official translation already exists in your target language, you can lock in that exact official name here so the AI doesn't guess.
- **Look for consistency**: If the same concept appears with multiple translations, unify them here before translation begins.
- **Verify domain accuracy**: Scientific or technical terms often have field-specific translations. Use your expertise to lock in the correct one.

> **Tip:** Do not skip this step! Refining your glossary now is the secret to high-quality output and will save you hours of manual correction later, especially on projects with dense terminology.

### Skip Glossary (Fast Track)

If you are working on a project where terminology consistency is less critical—such as a casual vlog or a simple interview—you can bypass the glossary stage entirely.

- After transcription completes, click **Skip & Translate Directly** instead of **Review Terminology**.
- TermSub will move straight to the translation phase without extracting or displaying the glossary.

---

## Stage 3: Translation

Once your glossary is reviewed (or skipped), click **Translate Subtitles**.

### What Happens

The **Translator Agent** processes your transcript segment by segment, using a sliding window approach that ensures each subtitle is translated with awareness of the surrounding context. The glossary you refined acts as a hard constraint: every standardized term is translated exactly as you specified.

### What You See

- The status changes to **Translating via OpenAI**.
- The **Processed Counter** advances in real time as segments are completed.
- When finished, the status changes to **Completed**, and the **Translated Subtitle Timeline** appears.

---

## Stage 4: The Visual Subtitle Timeline

After translation, you enter the refinement stage. The **Subtitle Timeline** is a scrollable, card-based editor that gives you pixel-level control over your subtitles.

### Navigating the Timeline

Each card represents one subtitle segment and displays:

- **Sequence number** (e.g., `#12`)
- **Timecode** (e.g., `⏱ [01:23.450 → 01:27.120]`)
- **Translated text** (editable inline)

### Inline Editing

- Click directly on any subtitle text to edit it.
- When you click away (blur), your change is **automatically saved** to the server.
- If you accidentally delete all text, the segment reverts to its original state and a warning appears in the Activity Log.

> **Tip:** The editor preserves RTL direction automatically. Arabic and Persian text will align to the right as expected.

### Splitting Segments

If a subtitle is too long or covers two distinct thoughts:

- Hover over the card and click the **Split** button (scissors icon).
- TermSub divides the segment at a natural break point and adjusts the timing.

### Adding Segments

If you need an extra subtitle line:

- Hover over any card and click the **Add** button (plus icon).
- A new blank segment is inserted directly below, ready for editing.

### Removing Segments

If a subtitle is redundant or incorrect:

- Hover over the card and click the **Remove** button (trash icon).
- The segment is deleted and sequence numbers are automatically renumbered.

### Global Find & Replace

At the top of the timeline panel, you will find the **Find & Replace** bar:

1. Type the text you want to find in the first field.
2. Type the replacement in the second field.
3. Click **Replace All**.

This applies across the **entire timeline** instantly—ideal for catching a mistranslated name or a repeated typo after the AI pass.

---

## Stage 5: Export & Integration

When you are satisfied with your subtitles, export them in the format that fits your post-production pipeline.

### Available Formats

Click any format button in the **Download Subtitles & Translations** section:

| Format | Best For |
|--------|----------|
| **SRT** | Universal subtitle format. Compatible with virtually every NLE and media player. |
| **WebVTT** | Web streaming, HTML5 video players, and online platforms. |
| **TXT** | Plain-text transcript for scripts, captions, or archival use. |
| **JSON** | Structured data export for custom pipelines or third-party tools. |

### RTL Punctuation Fixes (Automatic)

If your target language is Persian, Arabic, or any other RTL language, TermSub **automatically applies punctuation fixes** during SRT export. This ensures that:

- Final punctuation marks (periods, question marks) appear on the correct side of the line.
- Mixed LTR/RTL text renders cleanly in standard players.
- You do not need to manually fix subtitle files in a text editor before delivery.

### Using Your Exported Files

#### Playback & Review

To review your subtitles alongside the video before final rendering:

- Open **VLC Media Player**.
- Play your original video file.
- Drag and drop the exported `.srt` file directly onto the VLC window.
- VLC will load the subtitles instantly for synchronized playback.

#### Professional Post-Production

For final delivery, import your subtitle file directly into your Non-Linear Editor:

**Adobe Premiere Pro**
- Go to **File > Import** and select your `.srt` file.
- Drag the imported subtitle clip onto a video track above your main footage.
- Premiere Pro renders the subtitles as native captions, fully editable inside the timeline.

**DaVinci Resolve**
- Open the **Edit** page.
- Right-click in the Media Pool and select **Import Media**.
- Choose your `.srt` or `.vtt` file.
- Resolve places the subtitles on a dedicated subtitle track with per-line timing intact.

**Avid Media Composer**
- Use the **Subtitle Tool** or a compatible plugin to import SRT files.
- Most modern Avid workflows support direct SRT ingestion via third-party tools or the built-in Titler+.

**Web & Streaming**
- Upload the `.vtt` file alongside your video asset to platforms like YouTube, Vimeo, or your own HTML5 player.
- Reference the VTT file in a `<track>` element for standards-compliant captions.

---

## Tips for Best Results

- **Upload clean audio**: The clearer your source audio, the more accurate the initial transcription. Avoid heavy background music or competing speakers when possible.
- **Refine the glossary before translating**: A two-minute glossary review prevents hours of timeline correction.
- **Use Find & Replace before manual edits**: If you spot a systemic translation issue, fix it globally first, then fine-tune individual cards.
- **Export SRT for maximum compatibility**: SRT is the safest choice when you are unsure what your editor or platform expects.
- **Keep your API key handy**: The key is stored in your browser, but clearing cookies will remove it. Bookmark the OpenAI Platform key page for quick access.

---

*TermSub — Seamless translation. Consistent terminology. Production-ready subtitles.*
