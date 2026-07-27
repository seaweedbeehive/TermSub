"""Text Context Analysis Agent — Unified Extraction Call for plain text documents.

Mirrors the video pipeline's unified extraction call
(app.services.context_analysis_service) but uses prompts tailored for written
documents rather than video transcripts, and additionally auto-detects the
source language when the user didn't specify one. All video code remains
untouched.
"""

import json
import re
from typing import Any, cast

from sqlalchemy.orm import make_transient

from app.agents.translator import DEFAULT_TRANSLATION_MODEL
from app.core.languages import LANGUAGE_NAMES
from app.db.session import SessionLocal
from app.models.video import Segment, Term, Video, VideoStatus
from app.services.context_analysis_service import (
    _calculate_term_budget,
    _get_openai_client,
)
from app.services.progress_service import get_progress_tracker


def _build_text_context_prompt(
    full_text: str,
    target_language: str,
    source_language: str | None,
    term_budget: int,
) -> str:
    target_lang_name = LANGUAGE_NAMES.get(target_language, target_language)
    source_clause = (
        f"The document is written in {source_language}."
        if source_language and source_language != "auto"
        else (
            "Detect the source language of the document and report it "
            "in 'detected_source_language'."
        )
    )

    return f"""You are analyzing a written document to prepare it for professional translation into {target_lang_name}.

STEP 1 — IDENTIFY THE DOMAIN:
Read the document and identify what specialized subject matter it covers, in your own words
(e.g. "classical music theory and composition", "civil engineering", "criminal law procedure",
"cognitive behavioral therapy", "no specialized domain — general content"). Use this classification
to decide what KINDS of terms matter for this specific content — the categories below are examples
of the pattern to follow, not an exhaustive list:
- Political content → political systems, ideologies, governance concepts, political actors
- Medical content → diseases/conditions, procedures and treatments, anatomy, pharmaceuticals
- Psychological content → disorders, therapeutic approaches, cognitive concepts, assessment tools
- Sociological content → social structures, stratification concepts, social processes, methodologies
- Any other specialized domain → identify the equivalent categories yourself (e.g. for classical
  music: musical forms, compositional techniques, instrumentation, historical periods/movements;
  for law: legal doctrines, procedural terms, case citations; for cooking: techniques, equipment,
  ingredient science)

STEP 2 — EXTRACT TERMINOLOGY:
Extract approximately {term_budget} key terms using the domain-appropriate categories from Step 1,
plus named entities (people, organizations, theories, products, places) — all as they appear in the
SOURCE LANGUAGE of the document, with their STANDARD {target_lang_name} translations.

STEP 3 — BUILD A STYLE GUIDE:
Determine the tone and register a translator should use: is this educational, technical, academic,
literary, or promotional content? What tone and formality would resonate with {target_lang_name}
readers? Are there cultural considerations for the translation?

FULL DOCUMENT:
{full_text}

{source_clause}

TARGET LANGUAGE: {target_lang_name}

Respond in JSON format:
{{
  "detected_source_language": "<ISO-639-1 code or language name>",
  "detected_domain": "<the specialized subject matter you identified in Step 1, in your own words>",
  "main_topic": "<one-sentence summary of the document's subject, in {target_lang_name}>",
  "sub_topics": ["<topic 1>", "<topic 2>"],
  "key_terms": [
    {{
      "original": "<term exactly as it appears in the source language — DO NOT translate>",
      "target_standard": "<standard {target_lang_name} translation>",
      "category": "<a category appropriate to the detected domain, e.g. Technical|Proper Noun|Key Concept, or a domain-specific one like Musical Form|Legal Doctrine>",
      "confidence": "high|medium|low"
    }}
  ],
  "named_entities": [
    {{
      "name": "<name exactly as it appears in the source language — DO NOT translate>",
      "type": "Person|Organization|Product|Place|Theory",
      "target_translation": "<{target_lang_name} translation or transliteration>"
    }}
  ],
  "translation_notes": "<any special notes about translation approach for this content, in {target_lang_name}>",
  "style_guide": {{
    "tone": "<e.g. formal, casual, professional, conversational>",
    "formality_level": <integer 1-5, where 1 is very casual and 5 is very formal>,
    "target_audience": "<description of the intended audience>",
    "style_notes": ["<specific style instruction 1>", "<specific style instruction 2>"],
    "language_considerations": {{"<key point>": "<explanation>"}}
  }}
}}

CRITICAL: The "original" and "name" fields must be in the document's source language; do NOT translate them.

EXAMPLE — CORRECT (English source, Farsi target):
  {{"original": "machine learning", "target_standard": "یادگیری ماشین"}}
EXAMPLE — WRONG (English source, Farsi target):
  {{"original": "یادگیری ماشین", "target_standard": "یادگیری ماشین"}}

Guidelines:
- Include approximately {term_budget} key terms.
- Focus on terms that appear multiple times or are central to the topic.
- Provide standard {target_lang_name} translations for the target fields.
- Do NOT include ordinary, everyday words (common verbs, generic nouns) just to
  reach the target count. If the document doesn't contain {term_budget}
  genuine specialized terms, return fewer.
"""  # noqa: E501


def _save_text_terms_bulk(
    video_id: str,
    key_terms: list[dict[str, Any]],
    progress_tracker: Any | None = None,
) -> None:
    """Save extracted text glossary terms to the Term table."""
    if not key_terms:
        return

    terms_to_insert = []
    for term_data in key_terms:
        original = term_data.get("original", "").strip()
        target_std = term_data.get("target_standard", "").strip()
        category = term_data.get("category", "Key Concept")

        if not original or not target_std:
            continue

        terms_to_insert.append(
            {
                "video_id": video_id,
                "original_term": original,
                "translated_term": f"[{category}] {target_std}",
                "standardized_term": target_std,
                "category": category,
                "frequency": 0,
                "is_standardized": False,
                "source": "auto",
            }
        )

    if not terms_to_insert:
        return

    with SessionLocal() as session:
        existing_terms = (
            session.query(Term.original_term).filter(Term.video_id == video_id).all()
        )
        existing_originals = {t.original_term for t in existing_terms}

        new_terms = [
            t for t in terms_to_insert if t["original_term"] not in existing_originals
        ]

        if new_terms:
            session.bulk_insert_mappings(Term.__mapper__, new_terms)
            session.commit()

        if progress_tracker:
            progress_tracker.info(
                "TEXT_CONTEXT_ANALYSIS",
                f"Saved {len(new_terms)} new terms from text context analysis",
                f"Skipped {len(terms_to_insert) - len(new_terms)} duplicates",
            )


def analyze_text_context(
    video_id: str,
    model_name: str = DEFAULT_TRANSLATION_MODEL,
) -> dict[str, Any]:
    """Analyze a text document, extract terminology, and build a style guide —
    all in a single OpenAI call (mirrors analyze_video_context)."""
    progress_tracker = get_progress_tracker(video_id, None)

    with SessionLocal() as session:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Text record not found: {video_id}")
        if video.status == VideoStatus.ERROR.value:
            raise RuntimeError(f"Text record {video_id} is in ERROR status")

        source_language = video.source_language or "auto"
        target_language = video.target_language
        if not target_language:
            raise ValueError("Target language is not set")

        segments = (
            session.query(Segment)
            .filter(Segment.video_id == video_id)
            .order_by(Segment.sequence_number)
            .all()
        )
        if not segments:
            raise ValueError("No segments found for text context analysis")

        full_text = "\n\n".join(
            f"[{seg.sequence_number}] {seg.original_text}" for seg in segments
        )
        segment_count = len(segments)
        term_budget = _calculate_term_budget(segment_count)

        video.status = VideoStatus.ANALYZING.value
        session.commit()
        make_transient(video)

    progress_tracker.start_step(
        "TEXT_CONTEXT_ANALYSIS",
        f"Analyzing {segment_count} text segments for domain, terminology, and style",
    )

    try:
        client = _get_openai_client()
        prompt = _build_text_context_prompt(
            full_text, target_language, source_language, term_budget
        )

        progress_tracker.update_progress(
            status=VideoStatus.ANALYZING.value,
            percent=0,
            current_step="Text Context Analysis",
            step_detail="Sending document to OpenAI for analysis...",
        )

        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=16384,
        )

        response_text = response.choices[0].message.content or ""
        json_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL
        )
        if json_match:
            response_text = json_match.group(1)
        response_text = response_text.strip()

        try:
            context_data = cast(dict[str, Any], json.loads(response_text))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse text context analysis: {e}") from e

        detected = context_data.get("detected_source_language", source_language)
        detected_domain = context_data.get("detected_domain", "unknown")
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.context_analysis = json.dumps(
                    context_data, ensure_ascii=False, indent=2
                )
                style_guide = context_data.get("style_guide")
                if style_guide:
                    video.style_guide = json.dumps(style_guide, ensure_ascii=False)
                if source_language == "auto" and detected:
                    video.source_language = detected
                # Skip the old intermediate CONTEXT_READY/GLOSSARY_EXTRACTING
                # statuses — this is now a single call, so there's no
                # meaningful midpoint between them to report.
                video.status = VideoStatus.TERMS_READY.value
                session.commit()
                make_transient(video)

        _save_text_terms_bulk(
            video_id, context_data.get("key_terms", []), progress_tracker
        )

        progress_tracker.end_step(
            f"Text context analysis complete. Domain: {detected_domain}. Found "
            f"{len(context_data.get('key_terms', []))} key terms."
        )
        progress_tracker.info(
            "TEXT_CONTEXT_ANALYSIS",
            f"Topic: {context_data.get('main_topic', 'Unknown')}",
            f"Domain: {detected_domain}",
        )

        return context_data

    except Exception as e:
        error_msg = str(e)
        progress_tracker.error("TEXT_CONTEXT_ANALYSIS", "Failed", error_msg)
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.ERROR.value
                video.error_message = f"Text context analysis failed: {error_msg}"
                session.commit()
        raise RuntimeError(f"Text context analysis failed: {error_msg}") from e


# Pass 2 ("Text Glossary Agent") has been removed — its job is now done in
# the same call as analyze_text_context() (see module docstring), mirroring
# the video pipeline's unified extraction call.
