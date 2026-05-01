from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the backend package importable when alembic is invoked from /backend.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402  - registers all model metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the Supabase URL from .env so we never hardcode credentials.
# Escape `%` for configparser — Supabase passwords often contain URL-encoded
# characters like `%40` (=`@`) which configparser would otherwise treat as
# interpolation syntax and reject.
settings = get_settings()
if settings.supabase_database_url:
    safe_url = settings.supabase_database_url.replace("%", "%%")
    config.set_main_option("sqlalchemy.url", safe_url)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    # PostGIS creates spatial_ref_sys etc. — never autogenerate against those.
    if type_ == "table" and name in {"spatial_ref_sys"}:
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
