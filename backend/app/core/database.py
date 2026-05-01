from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _build_engine() -> Engine:
    settings = get_settings()
    if not settings.supabase_database_url:
        raise RuntimeError(
            "SUPABASE_DATABASE_URL is not set. Copy backend/.env.example to "
            "backend/.env and paste the Supabase Postgres connection string."
        )
    return create_engine(
        settings.supabase_database_url,
        pool_pre_ping=True,
        future=True,
    )


engine: Engine = _build_engine() if get_settings().supabase_database_url else None  # type: ignore[assignment]

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
) if engine is not None else None


def get_db() -> Iterator[Session]:
    if SessionLocal is None:
        raise RuntimeError("Database session is not configured (missing SUPABASE_DATABASE_URL).")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
