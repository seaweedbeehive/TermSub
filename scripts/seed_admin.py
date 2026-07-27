"""Standalone utility to create the first admin user.

Run directly:

    python scripts/seed_admin.py [email]

If email is not provided as a CLI argument, the script will prompt for it
interactively. The password is always prompted securely and is never accepted
as a command-line argument, so it cannot leak into shell history or ps output.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

# Make imports work when the script is run directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from app.core.auth import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402


def _read_credentials() -> tuple[str, str]:
    """Return (email, password) from a CLI email arg and a secure prompt."""
    if len(sys.argv) >= 3:
        print(
            "Error: password cannot be passed as a command-line argument. "
            "Run: python scripts/seed_admin.py [email]",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Create the first TermSub admin account.")

    email = sys.argv[1].strip() if len(sys.argv) == 2 else input("Email: ").strip()
    while not email:
        print("Email is required.")
        email = input("Email: ").strip()

    password = getpass.getpass("Enter admin password (will not be shown): ")
    while len(password) < 8:
        print("Password must be at least 8 characters.")
        password = getpass.getpass("Enter admin password (will not be shown): ")

    confirm = getpass.getpass("Confirm admin password: ")
    while confirm != password:
        print("Passwords do not match.")
        password = getpass.getpass("Enter admin password (will not be shown): ")
        while len(password) < 8:
            print("Password must be at least 8 characters.")
            password = getpass.getpass("Enter admin password (will not be shown): ")
        confirm = getpass.getpass("Confirm admin password: ")

    return email, password


def main() -> None:
    email, password = _read_credentials()

    db = SessionLocal()
    try:
        existing_admin = db.query(User).filter(User.is_admin.is_(True)).first()
        if existing_admin:
            print(f"An admin account already exists: {existing_admin.email}")
            print("No new admin was created.")
            return

        admin = User(
            email=email,
            password_hash=hash_password(password),
            is_admin=True,
            is_active=True,
            is_email_verified=True,
            api_key_mode="byok",
            wants_updates=False,
        )
        db.add(admin)
        db.commit()

        print(f"\nSuccess: admin account created for {email}.")
        print(
            "Log in and provide a BYOK OpenAI API key to start using the admin account."
        )

    except SQLAlchemyError as exc:
        db.rollback()
        print(f"Database error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
