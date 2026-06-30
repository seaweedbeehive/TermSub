#!/usr/bin/env python3
"""Promote a user to admin by email address.

Usage:
    python scripts/make_admin.py user@example.com
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Load .env from the project root (two directories up from this script).
project_root = Path(__file__).resolve().parents[1]
load_dotenv(project_root / ".env")

from app.models.user import User  # noqa: E402


def make_admin(email: str) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in environment or .env file.")
        sys.exit(1)

    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        user = db.query(User).filter(User.email == email.lower().strip()).first()
        if not user:
            print("User not found")
            return

        user.is_admin = True
        db.commit()
        print(f"User {user.email} is now admin")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/make_admin.py <email>")
        sys.exit(1)

    make_admin(sys.argv[1])
