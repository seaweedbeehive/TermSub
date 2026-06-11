"""Upload service - handles video and text file uploads with security validation."""

import re
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.video import ContentType, Video, VideoStatus

# Allowed file extensions
ALLOWED_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".m4v",
    ".mpeg",
    ".mpg",
    ".mp3",
    ".wav",
    ".m4a",
    ".ogg",
}
ALLOWED_TEXT_EXTENSIONS = {".txt", ".srt", ".vtt"}
ALLOWED_EXTENSIONS = ALLOWED_VIDEO_EXTENSIONS | ALLOWED_TEXT_EXTENSIONS

# Allowed MIME types for content validation
ALLOWED_MIME_TYPES = {
    # Video formats
    "video/mp4",
    "video/x-matroska",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
    "video/mpeg",
    "video/x-m4v",
    # Audio formats
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/m4a",
    "audio/ogg",
    "audio/vorbis",
    # Text formats
    "text/plain",
    "text/vtt",
    "application/x-subrip",
    # Fallback for when python-magic is not installed
    "application/octet-stream",
}

# File size limits
MAX_FILE_SIZE_MB = 500
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Filename sanitization pattern - remove path traversal and dangerous chars
FILENAME_SANITIZE_PATTERN = re.compile(r"[^\w\s.-]", re.UNICODE)
PATH_TRAVERSAL_PATTERN = re.compile(r"\.\./|\\|~")


class UploadValidationError(ValueError):
    """Raised when file upload validation fails."""

    pass


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and injection attacks.

    Args:
        filename: Original filename from user upload

    Returns:
        Sanitized safe filename

    Raises:
        UploadValidationError: If filename contains dangerous patterns
    """
    if not filename:
        raise UploadValidationError("Filename cannot be empty")

    # Check for path traversal attempts
    if PATH_TRAVERSAL_PATTERN.search(filename):
        raise UploadValidationError("Invalid filename: path traversal detected")

    # Extract just the filename (no paths)
    safe_name = Path(filename).name

    # Check for null bytes
    if "\x00" in safe_name:
        raise UploadValidationError("Invalid filename: null bytes detected")

    # Remove dangerous characters but keep Unicode letters/numbers
    safe_name = FILENAME_SANITIZE_PATTERN.sub("_", safe_name)

    # Limit length
    if len(safe_name) > 255:
        name_part, ext = (
            safe_name[:250].rsplit(".", 1)
            if "." in safe_name[:250]
            else (safe_name[:250], "")
        )
        safe_name = f"{name_part}.{ext}" if ext else name_part

    # Ensure not empty after sanitization
    if not safe_name or safe_name == ".":
        raise UploadValidationError("Filename is invalid after sanitization")

    return safe_name


def validate_file_extension(filename: str) -> tuple[bool, str]:
    """Check if file has a valid extension.

    Args:
        filename: Filename to check

    Returns:
        Tuple of (is_valid, content_type)
    """
    ext = Path(filename).suffix.lower()
    if ext in ALLOWED_VIDEO_EXTENSIONS:
        return True, ContentType.VIDEO.value
    elif ext in ALLOWED_TEXT_EXTENSIONS:
        return True, ContentType.TEXT.value
    return False, ""


def detect_mime_type(file: UploadFile) -> str:
    """Detect MIME type from file content using python-magic.

    Args:
        file: Uploaded file object

    Returns:
        Detected MIME type string

    Raises:
        UploadValidationError: If MIME type detection fails
    """
    try:
        import magic
    except ImportError:
        # Fallback if python-magic not installed - just trust extension
        return "application/octet-stream"

    # Read first 8KB for MIME detection
    chunk = file.file.read(8192)
    file.file.seek(0)  # Reset position

    if not chunk:
        raise UploadValidationError("File is empty")

    try:
        mime = magic.from_buffer(chunk, mime=True)
        return mime
    except Exception as e:
        raise UploadValidationError(f"Failed to detect file type: {e}") from e


def validate_file_content(file: UploadFile, expected_content_type: str) -> None:
    """Validate file content matches expected type using MIME detection.

    Args:
        file: Uploaded file object
        expected_content_type: Expected content type ('video' or 'text')

    Raises:
        UploadValidationError: If content validation fails
    """
    mime_type = detect_mime_type(file)

    # Check if python-magic is available (not using fallback)
    is_fallback = mime_type == "application/octet-stream"

    if is_fallback:
        # When python-magic is not installed, we rely on extension validation only
        # This is less secure but prevents breaking uploads
        print(
            f"[Upload] Warning: python-magic not installed, "
            f"skipping MIME validation for {file.filename}"
        )
        return

    # Check if MIME type is in allowed list
    if mime_type not in ALLOWED_MIME_TYPES:
        # Special handling for text files which can have various MIME types
        if (
            expected_content_type == ContentType.TEXT.value
            and mime_type.startswith("text/")
        ):
            return

        raise UploadValidationError(
            f"Invalid file content type: {mime_type}. "
            f"Expected {expected_content_type} format."
        )

    # Verify content type matches expected (skip for octet-stream fallback)
    if mime_type != "application/octet-stream":
        if expected_content_type == ContentType.VIDEO.value:
            if not (mime_type.startswith("video/") or mime_type.startswith("audio/")):
                raise UploadValidationError(
                    f"File content ({mime_type}) does not match "
                    "expected video/audio format"
                )
        elif expected_content_type == ContentType.TEXT.value and not (
            mime_type.startswith("text/") or mime_type == "application/x-subrip"
        ):
            raise UploadValidationError(
                f"File content ({mime_type}) does not match expected text format"
            )


def validate_file_size(file: UploadFile) -> None:
    """Validate file size is within limits.

    Args:
        file: Uploaded file object

    Raises:
        UploadValidationError: If file is too large
    """
    # Try to get content length from header first
    content_length = file.size

    if content_length and content_length > MAX_FILE_SIZE_BYTES:
        raise UploadValidationError(
            f"File too large: {content_length / (1024 * 1024):.1f}MB. "
            f"Maximum allowed: {MAX_FILE_SIZE_MB}MB"
        )


def generate_unique_filename(original_filename: str) -> str:
    """Generate a unique filename with timestamp prefix to avoid collisions.

    Args:
        original_filename: Sanitized original filename

    Returns:
        Unique filename with timestamp
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = original_filename.replace(" ", "_")
    return f"{timestamp}_{safe_name}"


def validate_upload(file: UploadFile) -> tuple[str, str]:
    """Comprehensive file upload validation.

    Validates:
    - Filename safety (no path traversal)
    - File extension
    - File size
    - MIME type matches extension

    Args:
        file: Uploaded file object

    Returns:
        Tuple of (safe_filename, content_type)

    Raises:
        UploadValidationError: If any validation fails
    """
    if not file.filename:
        raise UploadValidationError("No filename provided")

    # Sanitize filename
    safe_filename = sanitize_filename(file.filename)

    # Validate extension
    is_valid, content_type = validate_file_extension(safe_filename)
    if not is_valid:
        raise UploadValidationError(
            f"Invalid file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Validate size
    validate_file_size(file)

    # Validate content type matches extension
    validate_file_content(file, content_type)

    return safe_filename, content_type


async def save_uploaded_file(
    file: UploadFile,
    target_language: str,
    source_language: str,
    db: Session,
) -> Video:
    """Save uploaded file to disk with security validation and create database record.

    Args:
        file: The uploaded file
        target_language: Target language for translation (e.g., "en", "fa")
        source_language: Source language (e.g., "en", "fa", or "auto")
        db: Database session

    Returns:
        Created Video record

    Raises:
        UploadValidationError: If file validation fails
        ValueError: If database operation fails
    """
    # Validate file (security checks)
    safe_filename, content_type = validate_upload(file)

    # Ensure upload directory exists
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename
    unique_filename = generate_unique_filename(safe_filename)
    file_path = upload_dir / unique_filename

    # Save file to disk with size tracking
    bytes_written = 0
    try:
        with open(file_path, "wb") as buffer:
            while chunk := file.file.read(8192):  # 8KB chunks
                bytes_written += len(chunk)

                # Check size during streaming
                if bytes_written > MAX_FILE_SIZE_BYTES:
                    buffer.close()
                    file_path.unlink(missing_ok=True)
                    raise UploadValidationError(
                        f"File exceeds maximum size of {MAX_FILE_SIZE_MB}MB"
                    )

                buffer.write(chunk)

        # Verify file was written
        if not file_path.exists():
            raise UploadValidationError("Failed to save file")

        if bytes_written == 0:
            file_path.unlink(missing_ok=True)
            raise UploadValidationError("File is empty")

    except UploadValidationError:
        raise
    except Exception as e:
        # Clean up partial file if it exists
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        raise UploadValidationError(f"Failed to save file: {str(e)}") from e
    finally:
        await file.close()

    # Convert "auto" to None for database (Whisper will auto-detect)
    db_source_language = None if source_language == "auto" else source_language

    # For text files, auto-detect doesn't make sense, so default to "en" if auto
    if content_type == ContentType.TEXT.value and db_source_language is None:
        db_source_language = "en"

    # Create database record
    try:
        video = Video(
            filename=safe_filename,  # Store sanitized name
            file_path=str(file_path),
            content_type=content_type,
            status=VideoStatus.UPLOADED.value,
            target_language=target_language,
            source_language=db_source_language,
        )
        db.add(video)
        db.commit()
        db.refresh(video)

        print(f"[Upload] Saved '{safe_filename}' ({content_type}) as {unique_filename}")
        return video

    except Exception as e:
        # Clean up file if DB fails
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        raise ValueError(f"Failed to create database record: {str(e)}") from e


# Keep old function name for backward compatibility
save_uploaded_video = save_uploaded_file
