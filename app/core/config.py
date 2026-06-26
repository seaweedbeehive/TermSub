from pathlib import Path

from pydantic_settings import BaseSettings

WEAK_JWT_SECRETS: frozenset[str] = frozenset(
    {
        "change-me-in-production",
        "",
        "secret",
        "secret-key",
        "secret_key",
        "your-secret-key",
        "your_secret_key",
        "jwt-secret",
        "jwt_secret",
        "supersecret",
        "super-secret",
        "test",
        "test-secret",
        "test_secret",
        "password",
        "123456",
        "admin",
    }
)


class Settings(BaseSettings):
    PROJECT_NAME: str = "TermSub"
    VERSION: str = "2.1.0"
    DATABASE_URL: str = "postgresql://termsub:termsub@db:5432/termsub"
    REDIS_URL: str = "redis://redis:6379/0"
    UPLOAD_DIR: Path = Path("uploads")
    EXPORT_DIR: Path = Path("exports")
    OPENAI_API_KEY: str | None = None
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 7
    ADMIN_API_KEY: str = ""

    # Email (Resend)
    RESEND_API_KEY: str | None = None
    RESEND_FROM_EMAIL: str = "TermSub <noreply@termsub.app>"
    FRONTEND_BASE_URL: str = "http://localhost:8000"

    class Config:
        env_file = ".env"
        extra = "ignore"


def _validate_jwt_secret() -> None:
    """Refuse to start with an empty or weak JWT signing secret."""
    secret = settings.JWT_SECRET_KEY
    if secret is None or str(secret).strip() == "":
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. "
            "Set a strong JWT_SECRET_KEY in your .env file "
            "before starting the application."
        )
    if str(secret).strip().lower() in WEAK_JWT_SECRETS:
        raise RuntimeError(
            "JWT_SECRET_KEY is set to a weak/default value. "
            "Set a strong, randomly generated JWT_SECRET_KEY in your .env file "
            "before starting the application."
        )


settings = Settings()
_validate_jwt_secret()
