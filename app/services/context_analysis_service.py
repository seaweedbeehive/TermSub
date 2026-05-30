"""Context Analysis Service - Pass 1 of Two-Pass Translation System.

Analyzes the entire transcript to extract context, topics, and key terminology
before translation begins. This ensures consistent, context-aware translations.

Refactored to use short-lived database sessions to prevent SQLite locking.
"""

import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session, make_transient

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.video import Video, VideoStatus, VideoDomain, Segment, Term
from app.services.progress_service import get_progress_tracker


def clean_and_load_json(raw_text: str) -> Any:
    """Robustly extract and parse JSON from an LLM response.
    
    Strips markdown code blocks, conversational prefix/suffix text,
    and trailing commas before parsing.
    
    Args:
        raw_text: Raw text from the model
        
    Returns:
        Parsed JSON data (dict or list)
        
    Raises:
        json.JSONDecodeError: If no valid JSON can be extracted
    """
    if not raw_text or not isinstance(raw_text, str):
        raise json.JSONDecodeError("Empty or non-string input", "", 0)
    
    cleaned = raw_text.strip()
    
    # If wrapped in markdown code block, extract content
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        cleaned = cleaned.strip()
    
    # If still has conversational garbage, find innermost JSON object/array
    if not (cleaned.startswith("{") or cleaned.startswith("[")):
        obj_start = cleaned.find("{")
        arr_start = cleaned.find("[")
        if obj_start == -1 and arr_start == -1:
            raise json.JSONDecodeError(
                f"No JSON object or array found. Raw: {cleaned[:500]}", cleaned, 0
            )
        start = min(x for x in [obj_start, arr_start] if x != -1)
        cleaned = cleaned[start:]
    
    # Find matching closing brace/bracket from the end
    if cleaned.startswith("{"):
        end = cleaned.rfind("}")
        if end == -1:
            raise json.JSONDecodeError(
                f"No closing brace found. Raw: {cleaned[:500]}", cleaned, 0
            )
        cleaned = cleaned[:end+1]
    elif cleaned.startswith("["):
        end = cleaned.rfind("]")
        if end == -1:
            raise json.JSONDecodeError(
                f"No closing bracket found. Raw: {cleaned[:500]}", cleaned, 0
            )
        cleaned = cleaned[:end+1]
    
    # Remove trailing commas before closing braces/brackets
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"{e}. Cleaned text: {cleaned[:500]}", cleaned, e.pos if e.pos else 0
        ) from e


# Domain-specific context analysis prompts
CONTEXT_ANALYSIS_PROMPTS = {
    VideoDomain.POLITICS.value: """You are analyzing a POLITICAL video transcript. Extract:

1. MAIN TOPIC: The central political theme (e.g., "Democratic transitions in the Middle East")
2. SUB-TOPICS: 3-5 specific political concepts covered
3. KEY TERMS: 10-20 political terminology items with their STANDARD {target_language} translations:
   - Political systems (democracy, authoritarianism, regime types)
   - Ideologies (liberalism, conservatism, socialism, nationalism)
   - Governance concepts (civil society, public policy, sovereignty)
   - Political actors (parties, movements, international organizations)
4. NAMED ENTITIES: Important people, organizations, treaties, political theories

IMPORTANT: For terms with multiple {target_language} translations, 
provide the MOST STANDARD/ACADEMIC translation used in {target_language} political discourse.""",

    VideoDomain.MEDICINE.value: """You are analyzing a MEDICAL video transcript. Extract:

1. MAIN TOPIC: The medical specialty or health topic (e.g., "Type 2 Diabetes Management")
2. SUB-TOPICS: 3-5 specific medical concepts covered
3. KEY TERMS: 10-20 medical terminology items with their STANDARD {target_language} translations:
   - Diseases and conditions
   - Medical procedures and treatments
   - Anatomy and physiology terms
   - Pharmaceuticals and dosages
4. NAMED ENTITIES: Medical organizations, diagnostic criteria (DSM, ICD), treatment protocols

IMPORTANT: Use the standard {target_language} medical terminology.""",

    VideoDomain.PSYCHOLOGY.value: """You are analyzing a PSYCHOLOGY video transcript. Extract:

1. MAIN TOPIC: The psychological domain (e.g., "Cognitive Behavioral Therapy for Anxiety")
2. SUB-TOPICS: 3-5 specific psychological concepts covered
3. KEY TERMS: 10-20 psychology terminology items with their STANDARD {target_language} translations:
   - Mental health disorders
   - Therapeutic approaches (CBT, psychoanalysis, etc.)
   - Cognitive concepts (perception, memory, learning)
   - Assessment tools and diagnostic criteria
4. NAMED ENTITIES: Psychological theories, test names (MMPI, Beck Depression Inventory), theorists

IMPORTANT: Use established {target_language} psychological terminology.""",

    VideoDomain.SOCIOLOGY.value: """You are analyzing a SOCIOLOGY video transcript. Extract:

1. MAIN TOPIC: The sociological theme (e.g., "Social Stratification and Inequality")
2. SUB-TOPICS: 3-5 specific sociological concepts covered
3. KEY TERMS: 10-20 sociology terminology items with their STANDARD {target_language} translations:
   - Social structures and institutions
   - Concepts of inequality and stratification
   - Social processes (socialization, urbanization)
   - Research methodologies
4. NAMED ENTITIES: Sociological theories, theorists (Weber, Durkheim, etc.), social movements

IMPORTANT: Use standard {target_language} sociological academic terminology.""",

    VideoDomain.GENERAL.value: """You are analyzing a video transcript. Extract:

1. MAIN TOPIC: The primary subject matter
2. SUB-TOPICS: 3-5 key themes or concepts covered
3. KEY TERMS: 10-20 important terminology items with their STANDARD {target_language} translations:
   - Technical jargon specific to the field
   - Multi-word concepts and compound terms
   - Academic or specialized vocabulary
   - Repeated key concepts central to understanding
4. NAMED ENTITIES: Important people, organizations, theories, products, places

IMPORTANT: Focus on terms that:
- Appear multiple times in the transcript
- Have established {target_language} translations in the field
- Are central to understanding the content"""
}


def build_context_analysis_prompt(full_transcript: str, domain: str, target_language: str) -> str:
    """Build the context analysis prompt for Pass 1."""
    
    domain_prompt = CONTEXT_ANALYSIS_PROMPTS.get(domain, CONTEXT_ANALYSIS_PROMPTS[VideoDomain.GENERAL.value])
    domain_prompt = domain_prompt.format(target_language=target_language)
    
    return f"""{domain_prompt}

FULL TRANSCRIPT:
{full_transcript}

Respond in JSON format:
{{
  "main_topic": "Brief description of the main topic (1 sentence)",
  "sub_topics": ["sub-topic 1", "sub-topic 2", "sub-topic 3"],
  "key_terms": [
    {{
      "original": "English term",
      "target_standard": "Standard {target_language} translation",
      "category": "Technical|Proper Noun|Key Concept",
      "confidence": "high|medium|low"
    }}
  ],
  "named_entities": [
    {{
      "name": "Entity name",
      "type": "Person|Organization|Theory|Product|Place",
      "target_translation": "{target_language} translation or transliteration"
    }}
  ],
  "translation_notes": "Any special notes about translation approach for this content"
}}

Guidelines:
- Extract 10-20 key terms maximum - focus on the most important
- For each term, provide the SINGLE best standard {target_language} translation
- Prioritize terms that appear multiple times in the transcript
- Include multi-word concepts (e.g., "cognitive behavioral therapy", not just "therapy")
- If a term has multiple valid translations, choose the most common/academic one"""


def analyze_video_context(
    video_id: str,
    db: Optional[Session] = None,  # Kept for backward compatibility, not used
    model_name: str = "gemini-2.5-flash"
) -> Dict[str, Any]:
    """
    Pass 1: Analyze video context and extract terminology.
    
    This function uses short-lived database sessions to avoid holding locks
    during the long-running Gemini API call.
    
    Phase 1: Fetch video and segments, build transcript
    Phase 2: Send to Gemini for analysis (NO session held)
    Phase 3: Save results to database
    
    Args:
        video_id: ID of the video to analyze
        db: Deprecated parameter (kept for backward compatibility)
        model_name: Gemini model to use
        
    Returns:
        Context analysis dictionary with topic, terms, and entities
    """
    from google import genai
    
    # Initialize progress tracker (uses short-lived sessions internally)
    progress_tracker = get_progress_tracker(video_id, None)
    
    # ========================================================================
    # PHASE 1: FETCH - Get video and segments with short-lived session
    # ========================================================================
    with SessionLocal() as session:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video not found: {video_id}")
        
        # Check if video is in ERROR status - abort early
        if video.status == VideoStatus.ERROR.value:
            raise RuntimeError(f"Video {video_id} is in ERROR status, aborting context analysis")
        
        # Extract all needed data before session closes
        domain = video.domain or VideoDomain.GENERAL.value
        target_language = video.target_language
        if not target_language:
            raise ValueError("Target language is not set for this video.")
        
        source_language = video.source_language or "original"
        segments = (
            session.query(Segment)
            .filter(Segment.video_id == video_id, Segment.language_code == source_language)
            .order_by(Segment.sequence_number)
            .all()
        )
        
        if not segments:
            raise ValueError("No segments found for context analysis")
        
        # Build full transcript while session is open
        full_transcript = "\n\n".join([
            f"[{seg.sequence_number}] {seg.original_text}"
            for seg in segments
        ])
        
        # Update status
        video.status = VideoStatus.ANALYZING.value
        session.commit()
        make_transient(video)  # Prevent detachment after commit
    
    progress_tracker.info("CONTEXT_ANALYSIS", f"Starting Pass 1: Context Analysis for {domain} domain")
    progress_tracker.start_step("CONTEXT_ANALYSIS", f"Analyzing {len(segments)} segments for context and terminology")
    
    # Build prompt
    prompt = build_context_analysis_prompt(full_transcript, domain, target_language)
    
    # ========================================================================
    # PHASE 2: ANALYZE - Call Gemini API (NO DATABASE SESSION)
    # ========================================================================
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        progress_tracker.update_progress(
            status=VideoStatus.ANALYZING.value,
            percent=0,
            current_step="Context Analysis",
            step_detail="Sending transcript to Gemini for analysis..."
        )
        
        print(f"[CONTEXT_ANALYSIS] Starting analysis of {len(segments)} segments (domain: {domain})")
        start_time = datetime.utcnow()
        
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        
        # Parse response
        response_text = response.text
        
        try:
            context_data = clean_and_load_json(response_text)
        except json.JSONDecodeError as e:
            progress_tracker.error("CONTEXT_ANALYSIS", "Failed to parse JSON response", str(e))
            raise RuntimeError(f"Failed to parse context analysis: {e}") from e
        
        # Log results
        key_terms_count = len(context_data.get("key_terms", []))
        entities_count = len(context_data.get("named_entities", []))
        
        progress_tracker.end_step(
            f"Context analysis complete in {elapsed:.1f}s. "
            f"Found {key_terms_count} key terms, {entities_count} named entities."
        )
        progress_tracker.info(
            "CONTEXT_ANALYSIS",
            f"Pass 1 Complete: {context_data.get('main_topic', 'Unknown topic')}",
            f"Terms: {key_terms_count}, Entities: {entities_count}"
        )
        
        print(f"[CONTEXT_ANALYSIS] ✓ Complete in {elapsed:.1f}s")
        print(f"[CONTEXT_ANALYSIS] Topic: {context_data.get('main_topic', 'N/A')}")
        print(f"[CONTEXT_ANALYSIS] Terms: {key_terms_count}, Entities: {entities_count}")
        
        # ========================================================================
        # PHASE 3: SAVE - Store results with short-lived session
        # ========================================================================
        # Save context analysis to video
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.context_analysis = json.dumps(context_data, ensure_ascii=False, indent=2)
                video.status = VideoStatus.CONTEXT_READY.value
                session.commit()
                make_transient(video)
        
        # Save key terms using bulk insert for efficiency
        _save_context_terms_bulk(
            video_id,
            context_data.get("key_terms", []),
            progress_tracker,
            target_language=target_language
        )
        
        return context_data
        
    except Exception as e:
        error_msg = str(e)
        progress_tracker.error("CONTEXT_ANALYSIS", "Context analysis failed", error_msg)
        
        # Update error status with short session
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.ERROR.value
                video.error_message = f"Context analysis failed: {error_msg}"
                session.commit()
                make_transient(video)
        
        raise RuntimeError(f"Context analysis failed: {error_msg}") from e


def _looks_like_english_fallback(text: str, original: str, target_language: str) -> bool:
    """Check if a translation looks like an untranslated English fallback.
    
    Script-agnostic: uses target_language code to decide what constitutes
    a real translation vs. a raw English string.
    
    Args:
        text: The candidate translation
        original: The original English/source term
        target_language: ISO language code (e.g., 'de', 'fa', 'es')
        
    Returns:
        True if the text appears to be an English fallback
    """
    if not text or not isinstance(text, str):
        return True
    
    # English target is never a fallback
    if target_language == "en":
        return False
    
    # Non-Latin script families
    non_latin_patterns = {
        "fa": r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]',
        "ar": r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]',
        "ur": r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]',
        "ru": r'[\u0400-\u04FF\u0500-\u052F]',
        "uk": r'[\u0400-\u04FF\u0500-\u052F]',
        "zh": r'[\u4E00-\u9FFF\u3400-\u4DBF]',
        "ja": r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]',
        "ko": r'[\uAC00-\uD7AF\u1100-\u11FF]',
        "el": r'[\u0370-\u03FF\u1F00-\u1FFF]',
        "he": r'[\u0590-\u05FF\uFB1D-\uFB4F]',
        "th": r'[\u0E00-\u0E7F]',
        "hi": r'[\u0900-\u097F]',
    }
    
    pattern = non_latin_patterns.get(target_language)
    if pattern:
        return not bool(re.search(pattern, text))
    
    # For Latin-script languages (de, fr, es, it, pt, etc.)
    # If identical to source, it's a fallback
    if text.lower().strip() == original.lower().strip():
        return True
    
    # If it contains accented characters typical of European languages,
    # treat it as a real translation
    accented = re.search(
        r'[àáâãäåæçèéêëìíîïðñòóôõöøùúûüýÿßÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝŸąćęłńóśźżĄĆĘŁŃÓŚŹŻ]',
        text
    )
    return not bool(accented)


def _save_context_terms_bulk(
    video_id: str,
    key_terms: List[Dict[str, Any]],
    progress_tracker=None,
    target_language: str = "en"
) -> None:
    """Save extracted context terms to database using bulk insert for efficiency.
    
    Args:
        video_id: ID of the video
        key_terms: List of term dictionaries from context analysis
        progress_tracker: Optional progress tracker for logging
        target_language: Target language code for script-aware overwrite guard
    """
    if not key_terms:
        return
    
    # Prepare term data for bulk insert
    terms_to_insert = []
    
    for term_data in key_terms:
        original = term_data.get("original", "").strip()
        target_std = term_data.get("target_standard", "").strip()
        category = term_data.get("category", "Key Concept")
        
        if not original or not target_std:
            continue
        
        terms_to_insert.append({
            "video_id": video_id,
            "original_term": original,
            "translated_term": f"[{category}] {target_std}",
            "category": category,
            "frequency": 0,  # Will be updated during actual translation
            "is_standardized": False,
        })
    
    if not terms_to_insert:
        return
    
    # Use bulk upsert with a single session
    with SessionLocal() as session:
        # Fetch full existing term records for this video
        existing_terms = (
            session.query(Term)
            .filter(Term.video_id == video_id)
            .all()
        )
        existing_map = {t.original_term.lower(): t for t in existing_terms}
        
        new_terms = []
        updated_count = 0
        
        for t in terms_to_insert:
            original_lower = t["original_term"].lower()
            existing = existing_map.get(original_lower)
            
            if existing:
                # Script-agnostic guard: don't overwrite a real translation with English fallback
                existing_translation = existing.translated_term or ""
                new_translation = t["translated_term"] or ""
                # Strip category prefix for comparison
                existing_plain = re.sub(r'^\[.*?\]\s*', '', existing_translation)
                new_plain = re.sub(r'^\[.*?\]\s*', '', new_translation)
                
                if target_language != "en":
                    existing_is_fallback = _looks_like_english_fallback(
                        existing_plain, existing.original_term, target_language
                    )
                    new_is_fallback = _looks_like_english_fallback(
                        new_plain, existing.original_term, target_language
                    )
                    # If existing is good and new is English fallback, skip update
                    if not existing_is_fallback and new_is_fallback:
                        continue
                
                # Otherwise update the record
                existing.translated_term = new_translation
                existing.category = t["category"]
                updated_count += 1
            else:
                new_terms.append(t)
        
        # Bulk insert new terms
        if new_terms:
            session.bulk_insert_mappings(Term, new_terms)
        
        session.commit()
        
        if progress_tracker:
            progress_tracker.info(
                "CONTEXT_TERMS",
                f"Saved {len(new_terms)} new terms, updated {updated_count} existing",
                f"Total processed: {len(terms_to_insert)}"
            )


def get_context_glossary(video_id: str) -> Dict[str, str]:
    """
    Extract the context glossary from video's context_analysis.
    
    Args:
        video_id: ID of the video
        
    Returns:
        Dictionary mapping English terms to target language translations
    """
    with SessionLocal() as session:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video or not video.context_analysis:
            return {}
        
        try:
            context_data = json.loads(video.context_analysis)
            glossary = {}
            
            # Add key terms
            for term in context_data.get("key_terms", []):
                original = term.get("original", "").strip()
                target_std = term.get("target_standard", "").strip()
                if original and target_std:
                    glossary[original.lower()] = target_std
            
            # Add named entities
            for entity in context_data.get("named_entities", []):
                name = entity.get("name", "").strip()
                target_trans = entity.get("target_translation", "").strip()
                if name and target_trans:
                    glossary[name.lower()] = target_trans
            
            return glossary
        except (json.JSONDecodeError, KeyError):
            return {}


def extract_glossary(
    video_id: str,
    style_guide: Optional[Dict[str, Any]] = None,
    model_name: str = "gemini-2.5-flash"
) -> Dict[str, Any]:
    """
    Pass 2: Extract glossary/terms using the style guide.
    
    This is the Glossary Agent step of the Two-Pass system. It uses the style
    guide from Pass 1 to extract and standardize terminology.
    
    Uses short-lived database sessions to prevent SQLite locking.
    
    Args:
        video_id: ID of the video to extract glossary from
        style_guide: Style guide from analyze_video_context (optional)
        model_name: Gemini model to use
        
    Returns:
        Dictionary with key_terms list and other glossary data
    """
    from google import genai
    
    # Initialize progress tracker
    progress_tracker = get_progress_tracker(video_id, None)
    
    # ========================================================================
    # PHASE 1: FETCH - Get video and segments
    # ========================================================================
    with SessionLocal() as session:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video not found: {video_id}")
        
        # Check if video is in ERROR status - abort early
        if video.status == VideoStatus.ERROR.value:
            raise RuntimeError(f"Video {video_id} is in ERROR status, aborting glossary extraction")
        
        # Get target language
        target_language = video.target_language
        if not target_language:
            raise ValueError("Target language is not set for this video.")
        
        # Get context analysis if available
        context_analysis = {}
        if video.context_analysis:
            try:
                context_analysis = json.loads(video.context_analysis)
            except json.JSONDecodeError:
                pass
        
        # Get segments for building transcript (source language only)
        source_language = video.source_language or "original"
        segments = (
            session.query(Segment)
            .filter(Segment.video_id == video_id, Segment.language_code == source_language)
            .order_by(Segment.sequence_number)
            .all()
        )
        
        if not segments:
            raise ValueError("No segments found for glossary extraction")
        
        # Build transcript
        full_transcript = "\n\n".join([
            f"[{seg.sequence_number}] {seg.original_text}"
            for seg in segments
        ])
        
        # Update status
        video.status = VideoStatus.GLOSSARY_EXTRACTING.value
        session.commit()
    
    progress_tracker.info("GLOSSARY", "Starting Pass 2: Glossary Extraction")
    
    # ========================================================================
    # PHASE 2: EXTRACT - Call Gemini API (NO DATABASE SESSION)
    # ========================================================================
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        # Build glossary extraction prompt
        main_topic = context_analysis.get("main_topic", "General content")
        sub_topics = context_analysis.get("sub_topics", [])
        
        prompt = f"""You are a Glossary Extraction Agent. Your task is to extract and standardize terminology.

CONTEXT FROM PREVIOUS ANALYSIS:
- Main Topic: {main_topic}
- Sub-topics: {', '.join(sub_topics) if sub_topics else 'Various related topics'}

FULL TRANSCRIPT:
{full_transcript}

Extract a comprehensive glossary of terms:

1. KEY TERMS (10-20 items): Technical terminology, jargon, and key concepts
   - original: The English term exactly as it appears
   - target_standard: The standard {target_language} translation
   - category: Technical | Proper Noun | Key Concept | Academic Term
   - confidence: high | medium | low

2. NAMED ENTITIES (5-10 items): People, organizations, products, places
   - name: The entity name
   - type: Person | Organization | Product | Place | Theory
   - target_translation: {target_language} translation or transliteration

Respond in JSON format:
{{
  "key_terms": [
    {{
      "original": "English term",
      "target_standard": "Standard {target_language} translation",
      "category": "Technical|Proper Noun|Key Concept|Academic Term",
      "confidence": "high|medium|low"
    }}
  ],
  "named_entities": [
    {{
      "name": "Entity name",
      "type": "Person|Organization|Product|Place|Theory",
      "target_translation": "{target_language} translation"
    }}
  ]
}}

Guidelines:
- Focus on terms that appear multiple times in the transcript
- Use the most common/academic {target_language} translation
- Include multi-word concepts (e.g., "cognitive behavioral therapy")
- Prioritize terms central to the topic"""

        progress_tracker.update_progress(
            status=VideoStatus.GLOSSARY_EXTRACTING.value,
            percent=10,
            current_step="Glossary Extraction",
            step_detail="Sending to Gemini for focused glossary extraction..."
        )
        
        print(f"[GLOSSARY] Starting glossary extraction for {len(segments)} segments")
        start_time = datetime.utcnow()
        
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        
        # Parse response
        response_text = response.text
        
        try:
            glossary_data = clean_and_load_json(response_text)
        except json.JSONDecodeError as e:
            progress_tracker.error("GLOSSARY", "Failed to parse JSON response", str(e))
            raise RuntimeError(f"Failed to parse glossary extraction: {e}") from e
        
        # Log results
        key_terms_count = len(glossary_data.get("key_terms", []))
        entities_count = len(glossary_data.get("named_entities", []))
        
        progress_tracker.info(
            "GLOSSARY",
            f"Glossary extraction complete in {elapsed:.1f}s",
            f"Terms: {key_terms_count}, Entities: {entities_count}"
        )
        
        print(f"[GLOSSARY] ✓ Complete in {elapsed:.1f}s")
        print(f"[GLOSSARY] Terms: {key_terms_count}, Entities: {entities_count}")
        
        # ========================================================================
        # PHASE 3: SAVE - Store glossary terms
        # ========================================================================
        # Merge context_analysis key_terms with glossary_data key_terms
        # (to ensure we don't lose terms from Pass 1)
        pass1_lookup = {
            t.get("original", "").lower(): t
            for t in context_analysis.get("key_terms", [])
        }
        
        # If Pass 1 has a real translation and Pass 2 returned English fallback,
        # keep Pass 1's translation instead
        for term in glossary_data.get("key_terms", []):
            original = term.get("original", "").lower()
            pass1_term = pass1_lookup.get(original)
            if not pass1_term:
                continue
            
            pass1_trans = pass1_term.get("target_standard", "")
            pass2_trans = term.get("target_standard", "")
            
            if target_language != "en":
                pass1_is_fallback = _looks_like_english_fallback(
                    pass1_trans, pass1_term.get("original", ""), target_language
                )
                pass2_is_fallback = _looks_like_english_fallback(
                    pass2_trans, term.get("original", ""), target_language
                )
                if not pass1_is_fallback and pass2_is_fallback:
                    term["target_standard"] = pass1_trans
        
        # Add any terms from context analysis that aren't in glossary_data
        existing_terms = {t.get("original", "").lower() for t in glossary_data.get("key_terms", [])}
        
        for term in context_analysis.get("key_terms", []):
            original = term.get("original", "").lower()
            if original and original not in existing_terms:
                glossary_data.setdefault("key_terms", []).append(term)
        
        # Save terms to database
        _save_context_terms_bulk(
            video_id,
            glossary_data.get("key_terms", []),
            progress_tracker,
            target_language=target_language
        )
        
        # Update video status
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.TERMS_READY.value
                session.commit()
        
        # Return merged data
        return {
            "key_terms": glossary_data.get("key_terms", []),
            "named_entities": glossary_data.get("named_entities", []),
            "main_topic": context_analysis.get("main_topic", ""),
            "sub_topics": context_analysis.get("sub_topics", [])
        }
        
    except Exception as e:
        error_msg = str(e)
        progress_tracker.error("GLOSSARY", "Glossary extraction failed", error_msg)
        
        # Update error status
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.ERROR.value
                video.error_message = f"Glossary extraction failed: {error_msg}"
                session.commit()
        
        raise RuntimeError(f"Glossary extraction failed: {error_msg}") from e


# Backward compatibility alias
analyze_context = analyze_video_context
