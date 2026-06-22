from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "TermSub"
    VERSION: str = "2.1.0"
    DATABASE_URL: str = "postgresql://termsub:termsub@db:5432/termsub"
    UPLOAD_DIR: Path = Path("uploads")
    EXPORT_DIR: Path = Path("exports")
    OPENAI_API_KEY: str | None = None

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
