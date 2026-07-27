"""Newsletter signup model for both standard and BYOK users."""

import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NewsletterSignup(Base):
    """A newsletter signup independent of a full user account.

    Used primarily for BYOK (bring-your-own-key) users who want product
    updates without creating a password-backed account.
    """

    __tablename__ = "newsletter_signups"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="byok")
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, nullable=False
    )
