"""Timecode parsing and formatting utilities.

Handles the SRT-style ``HH:MM:SS,mmm`` representation used by the frontend
editable timestamp fields and maps it to/from floating-point seconds stored
in the database.
"""

import re

_TIMECODE_REGEX = re.compile(
    r"^(?P<hours>\d{2}):(?P<minutes>\d{2}):(?P<seconds>\d{2}),(?P<millis>\d{3})$"
)


def parse_timestamp(value: str) -> float:
    """Parse an ``HH:MM:SS,mmm`` string into total seconds.

    Args:
        value: Timestamp string to parse.

    Returns:
        Total seconds as a float.

    Raises:
        ValueError: If the string does not match the expected format or contains
            an out-of-range component (e.g. minutes >= 60).
    """
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")

    match = _TIMECODE_REGEX.match(value.strip())
    if not match:
        raise ValueError(
            "Timestamp must be in HH:MM:SS,mmm format (e.g. 00:05:12,340)"
        )

    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    millis = int(match.group("millis"))

    if minutes >= 60 or seconds >= 60 or millis >= 1000:
        raise ValueError("Timestamp contains an out-of-range component")

    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def format_timestamp(seconds: float) -> str:
    """Format floating-point seconds as ``HH:MM:SS,mmm``.

    Args:
        seconds: Duration in seconds.

    Returns:
        SRT-style timestamp string.
    """
    total_millis = max(0, int(round(seconds * 1000)))
    millis = total_millis % 1000
    total_seconds = total_millis // 1000
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    mins = total_minutes % 60
    hrs = total_minutes // 60

    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    """Format floating-point seconds as ``HH:MM:SS.mmm``.

    Args:
        seconds: Duration in seconds.

    Returns:
        WebVTT-style timestamp string.
    """
    total_millis = max(0, int(round(seconds * 1000)))
    millis = total_millis % 1000
    total_seconds = total_millis // 1000
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    mins = total_minutes % 60
    hrs = total_minutes // 60

    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{millis:03d}"
