"""Thread/async-safe context for the active OpenAI API key.

Allows BYOK API keys supplied in request headers to be used by background
workers and services without threading the key through every function
signature.
"""

from contextvars import ContextVar

from app.core.config import settings

byok_api_key: ContextVar[str | None] = ContextVar("byok_api_key", default=None)


def get_effective_openai_key(provided_key: str | None = None) -> str | None:
    """Return the API key to use for an OpenAI call.

    Priority:
        1. Key explicitly passed to the caller.
        2. Key set in the current BYOK context (e.g. from a Celery task).
        3. Server-wide key from settings.
    """
    if provided_key:
        return provided_key
    try:
        ctx_key = byok_api_key.get()
        if ctx_key:
            return ctx_key
    except LookupError:
        pass
    return settings.OPENAI_API_KEY
