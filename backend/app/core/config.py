from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    vertex_ai_api_key: str = Field(
        default="", validation_alias="VERTEX_AI_API_KEY",
        description=(
            "Vertex AI Express Mode API key (starts with 'AQ.'). When set, "
            "preferred over GEMINI_API_KEY because Vertex offers higher "
            "rate limits and billing through GCP credit."
        ),
    )
    gcp_project: str = Field(
        default="", validation_alias="GCP_PROJECT",
        description=(
            "GCP project ID (e.g. 'poetic-emblem-490411-p0'). When set "
            "AND application-default credentials are present (via gcloud "
            "auth application-default login), VertexAIProvider switches "
            "to ADC mode and hits standard-tier quotas instead of "
            "Express Mode tier 1. Takes precedence over VERTEX_AI_API_KEY "
            "in the `auto` resolution."
        ),
    )
    gcp_location: str = Field(
        default="us-central1", validation_alias="GCP_LOCATION",
        description="Vertex AI region — only used in ADC mode.",
    )
    llm_provider: Literal["auto", "vertex", "gemini", "anthropic", "mock"] = Field(
        default="auto", validation_alias="LLM_PROVIDER"
    )
    vertex_rpm_cap: int | None = Field(
        default=None, validation_alias="VERTEX_RPM_CAP",
        description="Override the VertexAIProvider RPM throttle. None = use class default.",
    )
    vertex_daily_cap: int | None = Field(
        default=None, validation_alias="VERTEX_DAILY_CAP",
    )
    gemini_rpm_cap: int | None = Field(
        default=None, validation_alias="GEMINI_RPM_CAP",
    )
    gemini_daily_cap: int | None = Field(
        default=None, validation_alias="GEMINI_DAILY_CAP",
    )
    llm_cache_enabled: bool = Field(default=True, validation_alias="LLM_CACHE")

    chroma_persist_dir: str = Field(
        default=str(BACKEND_DIR / "chroma_db"),
        validation_alias="CHROMA_PERSIST_DIR",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
