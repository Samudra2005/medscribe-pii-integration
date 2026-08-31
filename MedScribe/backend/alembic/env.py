"""
Alembic environment configuration.
Runs migrations using the SYNC database URL (psycopg2) even though the
app itself uses async (asyncpg) at runtime -- this is the standard,
well-documented pattern: Alembic's migration runner is synchronous
internally, and mixing that concern with our async app engine would add
complexity for no benefit, since migrations run once at deploy time,
not per-request.
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make "app" importable when Alembic runs from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402  (imports ALL models via __init__.py)

config = context.config
settings = get_settings()

# Inject our real DB URL at runtime instead of reading a static value
# from alembic.ini -- keeps .env as the single source of truth.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_SYNC)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is what Alembic diffs against to autogenerate migrations.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL scripts without a live DB connection (rarely used here, but standard boilerplate)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the live DB and apply migrations directly -- what we'll actually use."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,        # detect column type changes, not just add/drop
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()