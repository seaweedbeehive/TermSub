"""Text Context Analysis Agent — Pass 1 + Pass 2 for plain text documents.

Mirrors the video context-analysis logic but uses prompts tailored for written
text rather than video transcripts.  All video code remains untouched.
"""

import contextlib
import json
import re
from datetime import datetime
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
        else "Detect the source language of the document and report it in 'detected_source_language'."
    )

    return f"""You are a Context Analysis Agent for written text documents.

Your task is to read the document below and produce a structured analysis to help
a professional translator produce consistent, high-quality {target_lang_name} output.

FULL DOCUMENT:
{full_text}

{source_clause}

TARGET LANGUAGE: {target_lang_name}

Respond in JSON format:
{{
  "detected_source_language": "<ISO-639-1 code or language name>",
  "main_topic": "<one-sentence summary of the document's subject>",
  "sub_topics": ["<topic 1>", "<topic 2>"],
  "key_terms": [
    {{
      "original": "<term exactly as it appears in the source language>",
      "target_standard": "<standard {target_lang_name} translation>",
      "category": "Technical|Proper Noun|Key Concept|Academic Term",
      "confidence": "high|medium|low"
    }}
  ],
  "named_entities": [
    {{
      "name": "<name exactly as it appears in the source language>",
      "type": "Person|Organization|Product|Place|Theory",
      "target_translation": "<{target_lang_name} translation or transliteration>"
    }}
  ]
}}

Guidelines:
- Include approximately {term_budget} key terms.
- Focus on terms that appear multiple times or are central to the topic.
- The "original" and "name" fields must be in the document's source language; do NOT translate them.
- Provide standard {target_lang_name} translations for the target fields.
- Do NOT include ordinary, everyday words (common verbs, generic nouns) just to
  reach the target count. If the document doesn't contain {term_budget}
  genuine specialized terms, return fewer.
"""


def _build_text_glossary_prompt(
    full_text: str,
    context_analysis: dict[str, Any],
    target_language: str,
    source_language: str | None,
    term_budget: int,
) -> str:
    target_lang_name = LANGUAGE_NAMES.get(target_language, target_language)
    main_topic = context_analysis.get("main_topic", "General content")
    sub_topics = context_analysis.get("sub_topics", [])
    source_clause = (
        f"The document is written in {source_language}."
        if source_language and source_language != "auto"
        else "The source language was detected during context analysis."
    )

    return f"""You are a Glossary Extraction Agent for written text documents.

You have already received an initial context analysis; now refine and standardize
terminology for translation into {target_lang_name}.

CONTEXT:
- Main Topic: {main_topic}
- Sub-topics: {", ".join(sub_topics) if sub_topics else "Various related topics"}

FULL DOCUMENT:
{full_text}

{source_clause}

TARGET LANGUAGE: {target_lang_name}

Extract a comprehensive glossary:

1. KEY TERMS (approximately {term_budget} items): Technical terminology, jargon,
   and key concepts as they appear in the source language.
   - original: exact source-language term
   - target_standard: standard {target_lang_name} translation
   - category: Technical | Proper Noun | Key Concept | Academic Term
   - confidence: high | medium | low

2. NAMED ENTITIES (5-10 items): People, organizations, products, places.
   - name: exact source-language name
   - type: Person | Organization | Product | Place | Theory
   - target_translation: {target_lang_name} translation or transliteration

CRITICAL: The "original" and "name" fields must remain in the source language.
Do NOT translate them.

Respond in JSON format:
{{
  "key_terms": [
    {{
      "original": "<source term>",
      "target_standard": "<{target_lang_name} translation>",
      "category": "Technical|Proper Noun|Key Concept|Academic Term",
      "confidence": "high|medium|low"
    }}
  ],
  "named_entities": [
    {{
      "name": "<source name>",
      "type": "Person|Organization|Product|Place|Theory",
      "target_translation": "<{target_lang_name} translation>"
    }}
  ]
}}

Guidelines:
- Do NOT include ordinary, everyday words (common verbs, generic nouns) just to
  reach the target count. If the document doesn't contain {term_budget}
  genuine specialized terms, return fewer.
"""


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
            session.query(Term.original_term)
            .filter(Term.video_id == video_id)
            .all()
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
                "TEXT_GLOSSARY",
                f"Saved {len(new_terms)} new terms from text glossary extraction",
                f"Skipped {len(terms_to_insert) - len(new_terms)} duplicates",
            )


def analyze_text_context(
    video_id: str,
    model_name: str = DEFAULT_TRANSLATION_MODEL,
) -> dict[str, Any]:
    """Pass 1: analyze a text document and extract initial context/terms."""
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
        f"Analyzing {segment_count} text segments for context and terminology",
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
            temperature=0.3,
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
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.context_analysis = json.dumps(
                    context_data, ensure_ascii=False, indent=2
                )
                video.status = VideoStatus.CONTEXT_READY.value
                if source_language == "auto" and detected:
                    video.source_language = detected
                session.commit()
                make_transient(video)

        progress_tracker.end_step(
            f"Text context analysis complete. Found "
            f"{len(context_data.get('key_terms', []))} key terms."
        )
        progress_tracker.info(
            "TEXT_CONTEXT_ANALYSIS",
            f"Topic: {context_data.get('main_topic', 'Unknown')}",
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


def extract_text_glossary(
    video_id: str,
    model_name: str = DEFAULT_TRANSLATION_MODEL,
) -> dict[str, Any]:
    """Pass 2: refine and standardize terminology for a text document."""
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

        context_analysis = {}
        if video.context_analysis:
            with contextlib.suppress(json.JSONDecodeError):
                context_analysis = json.loads(video.context_analysis)

        segments = (
            session.query(Segment)
            .filter(Segment.video_id == video_id)
            .order_by(Segment.sequence_number)
            .all()
        )
        if not segments:
            raise ValueError("No segments found for text glossary extraction")

        full_text = "\n\n".join(
            f"[{seg.sequence_number}] {seg.original_text}" for seg in segments
        )
        segment_count = len(segments)
        term_budget = _calculate_term_budget(segment_count)

        video.status = VideoStatus.GLOSSARY_EXTRACTING.value
        session.commit()

    progress_tracker.start_step(
        "TEXT_GLOSSARY",
        f"Extracting standardized glossary for {segment_count} segments",
    )

    try:
        client = _get_openai_client()
        prompt = _build_text_glossary_prompt(
            full_text,
            context_analysis,
            target_language,
            source_language,
            term_budget,
        )

        progress_tracker.update_progress(
            status=VideoStatus.GLOSSARY_EXTRACTING.value,
            percent=10,
            current_step="Text Glossary Extraction",
            step_detail="Sending document to OpenAI for glossary extraction...",
        )

        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
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
            glossary_data = cast(dict[str, Any], json.loads(response_text))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse text glossary: {e}") from e

        # Merge with context-analysis terms to avoid dropping Pass 1 terms.
        existing_terms = {
            t.get("original", "").lower()
            for t in glossary_data.get("key_terms", [])
        }
        for term in context_analysis.get("key_terms", []):
            original = term.get("original", "").lower()
            if original and original not in existing_terms:
                glossary_data.setdefault("key_terms", []).append(term)

        _save_text_terms_bulk(
            video_id, glossary_data.get("key_terms", []), progress_tracker
        )

        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.TERMS_READY.value
                session.commit()

        progress_tracker.end_step(
            f"Text glossary extraction complete. "
            f"Saved {len(glossary_data.get('key_terms', []))} terms."
        )

        return {
            "key_terms": glossary_data.get("key_terms", []),
            "named_entities": glossary_data.get("named_entities", []),
            "main_topic": context_analysis.get("main_topic", ""),
            "sub_topics": context_analysis.get("sub_topics", []),
        }

    except Exception as e:
        error_msg = str(e)
        progress_tracker.error("TEXT_GLOSSARY", "Failed", error_msg)
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.ERROR.value
                video.error_message = f"Text glossary extraction failed: {error_msg}"
                session.commit()
        raise RuntimeError(f"Text glossary extraction failed: {error_msg}") from e
