from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models so they are registered with the metadata.
# This keeps Alembic autogenerate and Base.metadata.create_all() in sync.
from app.models.analytics import PageView, UsageEvent  # noqa: E402, F401
from app.models.job_queue import JobQueue  # noqa: E402, F401
from app.models.newsletter import NewsletterSignup  # noqa: E402, F401
from app.models.user import User, UserSession  # noqa: E402, F401
from app.models.video import (  # noqa: E402, F401
    ProcessingLog,
    Segment,
    Term,
    TermOccurrence,
    TranslationVariant,
    Video,
)
