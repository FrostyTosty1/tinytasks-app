from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine

from alembic import context

# --- Make sure the backend package is importable for Alembic ---
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Import models so SQLAlchemy registers them in Base.metadata for Alembic autogenerate.
from src import models  # noqa: F401, E402
from src.config import get_database_url  # noqa: E402
from src.db import Base  # noqa: E402

# Alembic Config object provides access to the .ini file values
config = context.config

# Setup logging configuration (from alembic.ini)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Define metadata for 'autogenerate' feature
target_metadata = Base.metadata

# Database URL must be provided explicitly via environment.
DATABASE_URL = get_database_url()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.
    This configures the context with just a URL, without an Engine.
    Useful for generating SQL scripts without DB connection.
    """
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,  # detect type changes in autogenerate
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.
    This connects to the database and runs the migration directly.
    """
    connectable = create_engine(DATABASE_URL, pool_pre_ping=True)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
