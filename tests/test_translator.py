"""Tests for the async OpenAI translator agent."""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import RateLimitError

from app.agents.translator import (
    MAX_CONCURRENT_CALLS,
    MAX_RETRIES,
    BatchResult,
    TranslationBatch,
    translate_batches_concurrently,
    translate_single_batch_with_retry,
)


@pytest.fixture
def anyio_backend() -> str:
    """Restrict anyio tests to asyncio only (trio is not installed)."""
    return "asyncio"


def _make_batch(
    batch_index: int = 0,
    segments: list[dict[str, Any]] | None = None,
) -> TranslationBatch:
    """Build a minimal translation batch."""
    return TranslationBatch(
        batch_index=batch_index,
        segments=segments
        or [{"id": 1, "sequence_number": 1, "original_text": "hello"}],
    )


def _make_valid_response(segment_sequence: int = 1, text: str = "salam") -> MagicMock:
    """Build a fake OpenAI chat response with valid JSON content."""
    payload = json.dumps(
        {
            "translations": [
                {
                    "sequence_number": segment_sequence,
                    "translated_text": text,
                    "extracted_terms": [],
                }
            ]
        }
    )
    message = MagicMock(content=payload)
    choice = MagicMock(message=message)
    response = MagicMock(choices=[choice])
    return response


def _make_client(side_effect: Any | None = None) -> MagicMock:
    """Build a fake AsyncOpenAI client."""
    client = MagicMock()
    if side_effect is not None:
        client.chat.completions.create = AsyncMock(side_effect=side_effect)
    else:
        client.chat.completions.create = AsyncMock(return_value=_make_valid_response())
    return client


@pytest.mark.anyio
async def test_translate_single_batch_with_retry_retries_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429 error should be retried and eventually succeed."""
    monkeypatch.setattr("app.agents.translator.RATE_LIMIT_DELAY", 0.001)
    monkeypatch.setattr("app.agents.translator.BASE_RETRY_DELAY", 0.001)

    batch = _make_batch()
    # Fail twice with RateLimitError, then succeed.
    side_effect = [
        RateLimitError("rate limited", response=MagicMock(), body=None),
        RateLimitError("rate limited", response=MagicMock(), body=None),
        _make_valid_response(),
    ]
    client = _make_client(side_effect=side_effect)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)

    result = await translate_single_batch_with_retry(
        batch=batch,
        client=client,
        model_name="gpt-5.4-mini",
        source_language="en",
        target_language="fa",
        progress_tracker=None,
        semaphore=semaphore,
    )

    assert result.success is True
    assert result.translations[0]["translated_text"] == "salam"
    assert client.chat.completions.create.call_count == 3


@pytest.mark.anyio
async def test_translate_single_batch_with_retry_fails_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After all retries are exhausted, a failed BatchResult is returned."""
    monkeypatch.setattr("app.agents.translator.RATE_LIMIT_DELAY", 0.001)
    monkeypatch.setattr("app.agents.translator.BASE_RETRY_DELAY", 0.001)

    batch = _make_batch()
    client = _make_client(
        side_effect=RateLimitError("rate limited", response=MagicMock(), body=None)
    )
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)

    result = await translate_single_batch_with_retry(
        batch=batch,
        client=client,
        model_name="gpt-5.4-mini",
        source_language="en",
        target_language="fa",
        progress_tracker=None,
        semaphore=semaphore,
    )

    assert result.success is False
    assert result.error is not None
    assert client.chat.completions.create.call_count == MAX_RETRIES


@pytest.mark.anyio
async def test_translate_batches_concurrently_respects_max_concurrency() -> None:
    """No more than MAX_CONCURRENT_CALLS batches should run at the same time."""
    batches = [_make_batch(i) for i in range(5)]
    active = 0
    max_active = 0

    async def _tracked_translate(**kwargs: Any) -> BatchResult:
        nonlocal active, max_active
        semaphore = kwargs["semaphore"]
        async with semaphore:
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1
        return BatchResult(batch_index=kwargs["batch"].batch_index, success=True)

    client = MagicMock()

    with patch(
        "app.agents.translator.translate_single_batch_with_retry",
        side_effect=_tracked_translate,
    ):
        results = await translate_batches_concurrently(
            video_id="vid-1",
            batches=batches,
            client=client,
            model_name="gpt-5.4-mini",
            source_language="en",
            target_language="fa",
            progress_tracker=None,
        )

    assert len(results) == len(batches)
    assert all(r.success for r in results)
    assert max_active <= MAX_CONCURRENT_CALLS


def test_fresh_semaphore_per_event_loop() -> None:
    """Simulate Celery reusing a worker thread: two separate asyncio.run calls."""
    batches = [_make_batch(i) for i in range(2)]

    async def _run() -> list[BatchResult]:
        client = MagicMock()
        with patch(
            "app.agents.translator.translate_single_batch_with_retry",
            new=AsyncMock(return_value=BatchResult(batch_index=0, success=True)),
        ):
            return await translate_batches_concurrently(
                video_id="vid-1",
                batches=batches,
                client=client,
                model_name="gpt-5.4-mini",
                source_language="en",
                target_language="fa",
                progress_tracker=None,
            )

    # Run twice in the same thread with separate event loops, as Celery does.
    result1 = asyncio.run(_run())
    result2 = asyncio.run(_run())

    assert len(result1) == len(batches)
    assert len(result2) == len(batches)
