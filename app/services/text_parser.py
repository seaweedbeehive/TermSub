"""Text parsing service - splits text files into segments for translation.

Refactored to use short-lived database sessions to prevent SQLite locking.
"""

import re
from pathlib import Path
from typing import Any

from app.db.session import SessionLocal
from app.models.video import Segment, Video, VideoStatus
from app.services.progress_service import get_progress_tracker


def split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences using regex.

    Handles common sentence endings (. ! ?) and avoids splitting on abbreviations.
    """
    # Clean up the text
    text = text.strip()
    if not text:
        return []

    # Regex pattern for sentence splitting
    # Matches sentence-ending punctuation followed by space and capital letter
    # or end of string
    sentence_endings = r"(?<=[.!?])\s+(?=[A-Z])|(?<=[.!?])\s*$"
    sentences = re.split(sentence_endings, text)

    # Clean up sentences
    cleaned = []
    for sent in sentences:
        sent = sent.strip()
        if sent:
            # Ensure sentence ends with punctuation
            if sent[-1] not in ".!?":
                sent += "."
            cleaned.append(sent)

    return cleaned


def parse_text_file(video_id: str) -> dict[str, Any]:
    """
    Parse a text file into segments for translation.

    Uses short-lived database sessions:
    - Phase 1: Get video info and file_path
    - Phase 2: Read file and split into sentences (NO session)
    - Phase 3: Save segments to database

    Args:
        video_id: ID of the video/text record

    Returns:
        Dict with video_id, status, and segment_count
    """
    # Initialize progress tracker (uses short-lived sessions internally)
    progress_tracker = get_progress_tracker(video_id, None)

    # ========================================================================
    # PHASE 1: Get video info with short-lived session
    # ========================================================================
    with SessionLocal() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video not found: {video_id}")

        # Check if video is in ERROR status - abort early
        if video.status == VideoStatus.ERROR.value:
            raise RuntimeError(
                f"Video {video_id} is in ERROR status, aborting text parsing"
            )

        # Validate it's a text file
        if video.content_type != "text":
            raise ValueError(f"Not a text file: {video_id}")

        # Extract needed data before closing session
        file_path_str = video.file_path
        filename = video.filename

        progress_tracker.info("TEXT_PARSE", f"Parsing text file: {filename}")

        # Update status
        video.status = VideoStatus.TRANSCRIBING.value
        db.commit()
        # No make_transient needed - we return primitives only

    # ========================================================================
    # PHASE 2: Read file and parse content (NO DATABASE SESSION)
    # ========================================================================
    try:
        # Read text file
        file_path = Path(file_path_str)
        if not file_path.exists():
            raise ValueError(f"File not found: {file_path_str}")

        text = file_path.read_text(encoding="utf-8")

        # Split into sentences
        progress_tracker.info("TEXT_PARSE", "Splitting text into sentences...")
        sentences = split_into_sentences(text)

        if not sentences:
            raise ValueError("No sentences found in text file")

        total_sentences = len(sentences)
        progress_tracker.info("TEXT_PARSE", f"Found {total_sentences} sentences")

        # ========================================================================
        # PHASE 3: Save segments with new short-lived session
        # ========================================================================
        with SessionLocal() as db:
            # Create segments in batches for better performance
            segments_to_add = []
            for idx, sentence in enumerate(sentences, 1):
                segment = Segment(
                    video_id=video_id,
                    sequence_number=idx,
                    start_time=0.0,  # No timestamps for text
                    end_time=0.0,
                    original_text=sentence,
                )
                segments_to_add.append(segment)

                # Update progress periodically
                if idx % 10 == 0 or idx == 1 or idx == total_sentences:
                    percent = int((idx / total_sentences) * 100)
                    progress_tracker.update_progress(
                        status=VideoStatus.TRANSCRIBING.value,
                        percent=percent,
                        current_step="Creating Segments",
                        step_detail=f"Processing sentence {idx}/{total_sentences}",
                        total_segments=total_sentences,
                        processed_segments=idx,
                        current_segment_index=idx,
                    )

            # Bulk insert all segments at once for efficiency
            db.add_all(segments_to_add)

            # Update video status
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.TRANSCRIBED.value  # Ready for translation
                video.progress_percent = 100
                video.total_segments = total_sentences
                video.processed_segments = total_sentences

            db.commit()

        progress_tracker.end_step(
            f"Text parsing complete! Created {total_sentences} segments"
        )

        # Return primitives only - ZERO LEAK POLICY
        return {
            "video_id": video_id,
            "status": VideoStatus.TRANSCRIBED.value,
            "segment_count": total_sentences,
            "success": True,
        }

    except Exception as e:
        error_msg = str(e)

        # Update error status with short session - ZERO LEAK POLICY
        # Re-query by ID, never use video object from try scope
        with SessionLocal() as db:
            video_record = db.query(Video).filter(Video.id == video_id).first()
            if video_record:
                video_record.status = VideoStatus.ERROR.value
                video_record.error_message = error_msg
                db.commit()

        progress_tracker.error("TEXT_PARSE", "Text parsing failed", error_msg)
        raise RuntimeError(f"Text parsing failed: {error_msg}") from e
