from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    PROJECT_NAME: str = "TermSub"
    VERSION: str = "0.1.0"
    DATABASE_URL: str = "sqlite:///./termsub.db"
    UPLOAD_DIR: Path = Path("uploads")
    EXPORT_DIR: Path = Path("exports")
    GEMINI_API_KEY: str

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
