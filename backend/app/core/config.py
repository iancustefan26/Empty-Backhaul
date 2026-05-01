from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_database_url: str = Field(
        default="",
        validation_alias="SUPABASE_DATABASE_URL",
        description="SQLAlchemy URL for the Supabase Postgres instance.",
    )
    app_env: str = Field(default="development", validation_alias="APP_ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    chroma_persist_dir: str = Field(
        default=str(BACKEND_DIR / "chroma_db"),
        validation_alias="CHROMA_PERSIST_DIR",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
