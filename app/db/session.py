"""Database session management with bulk operation support."""

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.video import Segment

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def bulk_upsert_segments(
    video_id: str, segment_data_list: list[dict[str, Any]]
) -> int:
    """Bulk upsert segments using dialect-specific upsert (SQLite)
    or fetch-then-update (PostgreSQL).

    Args:
        video_id: The video ID for all segments
        segment_data_list: List of dicts with keys: sequence_number, translated_text

    Returns:
        Number of rows affected
    """
    if not segment_data_list:
        return 0

    # SQLite fast path: native upsert
    if engine.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        db = SessionLocal()
        try:
            upsert_data = []
            for seg_data in segment_data_list:
                upsert_data.append(
                    {
                        "video_id": video_id,
                        "sequence_number": seg_data["sequence_number"],
                        "translated_text": seg_data.get("translated_text"),
                        "original_text": seg_data.get("original_text", ""),
                        "start_time": seg_data.get("start_time", 0.0),
                        "end_time": seg_data.get("end_time", 0.0),
                    }
                )

            stmt = sqlite_insert(Segment).values(upsert_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["video_id", "sequence_number"],
                set_={
                    "translated_text": stmt.excluded.translated_text,
                },
            )

            result = db.execute(stmt)
            db.commit()
            return result.rowcount
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    # PostgreSQL / generic path: fetch-then-update or insert
    db = SessionLocal()
    try:
        existing = {
            s.sequence_number: s
            for s in db.query(Segment).filter(Segment.video_id == video_id).all()
        }
        count = 0
        for seg_data in segment_data_list:
            seq = seg_data["sequence_number"]
            if seq in existing:
                existing[seq].translated_text = seg_data.get("translated_text")
                existing[seq].original_text = seg_data.get("original_text", "")
                existing[seq].start_time = seg_data.get("start_time", 0.0)
                existing[seq].end_time = seg_data.get("end_time", 0.0)
                count += 1
            else:
                db.add(
                    Segment(
                        video_id=video_id,
                        sequence_number=seq,
                        original_text=seg_data.get("original_text", ""),
                        translated_text=seg_data.get("translated_text"),
                        start_time=seg_data.get("start_time", 0.0),
                        end_time=seg_data.get("end_time", 0.0),
                    )
                )
                count += 1
        db.commit()
        return count
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def bulk_update_segment_translations(
    video_id: str, translations: list[dict[str, Any]]
) -> int:
    """Bulk update segment translations by sequence number.

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
        segments = db.query(Segment).filter(Segment.video_id == video_id).all()
        seq_to_segment = {s.sequence_number: s for s in segments}

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
    translations: list[dict[str, Any]],
) -> int:
    """Bulk update existing segment translations by sequence number.

    Args:
        video_id: The video ID
        translations: List of dicts with keys: sequence_number, translated_text

    Returns:
        Number of segments updated
    """
    if not translations:
        return 0

    db = SessionLocal()
    try:
        existing = db.query(Segment).filter(Segment.video_id == video_id).all()
        existing_seqs = {s.sequence_number: s for s in existing}

        saved_count = 0
        for trans in translations:
            seq_num = trans.get("sequence_number")
            translated_text = trans.get("translated_text", "").strip()
            if not seq_num or not translated_text:
                continue

            if seq_num in existing_seqs:
                existing_seqs[seq_num].translated_text = translated_text
                saved_count += 1

        db.commit()
        return saved_count

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
