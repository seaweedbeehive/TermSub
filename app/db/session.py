"""Database session management with bulk operation support."""

from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, insert, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.models.video import Segment

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def bulk_upsert_segments(video_id: str, segment_data_list: List[Dict[str, Any]]) -> int:
    """Bulk upsert segments using SQLAlchemy's insert().on_conflict_do_update() for SQLite.
    
    This function performs a bulk upsert (insert or update) of segment translations.
    It updates existing segments by matching (video_id, sequence_number, language_code)
    or inserts new ones.
    
    Args:
        video_id: The video ID for all segments
        segment_data_list: List of dicts with keys: sequence_number, translated_text, language_code
        
    Returns:
        Number of rows affected
        
    Example:
        segment_data = [
            {"sequence_number": 1, "translated_text": "Hello", "language_code": "de"},
            {"sequence_number": 2, "translated_text": "World", "language_code": "de"},
        ]
        count = bulk_upsert_segments("video-uuid", segment_data)
    """
    if not segment_data_list:
        return 0
    
    db = SessionLocal()
    try:
        # Build upsert data with video_id
        upsert_data = []
        for seg_data in segment_data_list:
            upsert_data.append({
                "video_id": video_id,
                "sequence_number": seg_data["sequence_number"],
                "translated_text": seg_data.get("translated_text"),
                "language_code": seg_data.get("language_code", "original"),
                # Preserve original fields if they exist, otherwise use defaults
                "original_text": seg_data.get("original_text", ""),
                "start_time": seg_data.get("start_time", 0.0),
                "end_time": seg_data.get("end_time", 0.0),
            })
        
        # SQLite upsert: insert or update on conflict
        stmt = sqlite_insert(Segment).values(upsert_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["video_id", "sequence_number", "language_code"],  # Conflict target
            set_={
                "translated_text": stmt.excluded.translated_text,
            }
        )
        
        result = db.execute(stmt)
        db.commit()
        
        return result.rowcount
        
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def bulk_update_segment_translations(video_id: str, translations: List[Dict[str, Any]]) -> int:
    """Bulk update segment translations by sequence number.
    
    This is more efficient than updating one-by-one when segments already exist.
    Uses a single UPDATE with CASE statement for SQLite.
    
    Args:
        video_id: The video ID
        translations: List of dicts with keys: sequence_number, translated_text
        
    Returns:
        Number of rows updated
    """
    if not translations:
        return 0
    
    db = SessionLocal()
    try:
        # Get all segment IDs for this video
        segments = db.query(Segment).filter(Segment.video_id == video_id).all()
        seq_to_segment = {s.sequence_number: s for s in segments}
        
        # Build update data
        update_count = 0
        for trans in translations:
            seq_num = trans.get("sequence_number")
            translated_text = trans.get("translated_text", "").strip()
            
            if seq_num and translated_text and seq_num in seq_to_segment:
                seq_to_segment[seq_num].translated_text = translated_text
                update_count += 1
        
        if update_count > 0:
            db.commit()
        
        return update_count
        
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def bulk_upsert_segment_translations(
    video_id: str,
    translations: List[Dict[str, Any]],
    target_language: str = "original",
    source_lookup: Optional[Dict[int, Dict[str, Any]]] = None,
) -> int:
    """Bulk upsert segment translations for a specific language track.
    
    For multi-language support: updates existing segments with the target language
    code if they exist, or inserts new segment rows copying timeline data from
    the source segment.
    
    Args:
        video_id: The video ID
        translations: List of dicts with keys: sequence_number, translated_text
        target_language: Language code to tag segments with (e.g., 'de', 'fa')
        source_lookup: Dict mapping sequence_number -> source segment dict
            (must include start_time, end_time, original_text for new rows)
        
    Returns:
        Number of segments saved (updated or inserted)
    """
    if not translations:
        return 0
    
    db = SessionLocal()
    try:
        # Fetch existing segments for this video + target language
        existing = (
            db.query(Segment)
            .filter(Segment.video_id == video_id, Segment.language_code == target_language)
            .all()
        )
        existing_seqs = {s.sequence_number: s for s in existing}
        
        saved_count = 0
        for trans in translations:
            seq_num = trans.get("sequence_number")
            translated_text = trans.get("translated_text", "").strip()
            if not seq_num or not translated_text:
                continue
            
            if seq_num in existing_seqs:
                # Update existing target-language segment
                existing_seqs[seq_num].translated_text = translated_text
                saved_count += 1
            elif source_lookup and seq_num in source_lookup:
                # Insert new segment row for this language track
                src = source_lookup[seq_num]
                new_seg = Segment(
                    video_id=video_id,
                    sequence_number=seq_num,
                    start_time=src.get("start_time", 0.0),
                    end_time=src.get("end_time", 0.0),
                    original_text=src.get("original_text", ""),
                    translated_text=translated_text,
                    language_code=target_language,
                )
                db.add(new_seg)
                saved_count += 1
            else:
                # Fallback: insert with minimal data
                new_seg = Segment(
                    video_id=video_id,
                    sequence_number=seq_num,
                    start_time=0.0,
                    end_time=0.0,
                    original_text="",
                    translated_text=translated_text,
                    language_code=target_language,
                )
                db.add(new_seg)
                saved_count += 1
        
        db.commit()
        return saved_count
        
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
