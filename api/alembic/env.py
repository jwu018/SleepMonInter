"""The entry point Alembic runs: which database to use and which tables are ours."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from app import models  # noqa: F401  (importing registers the tables on Base.metadata)
from app.db import Base, get_engine

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    """Only look at tables we define. Tables owned by Supabase are never compared or changed."""
    if type_ == "schema":
        return name in (None, "public")
    if type_ == "table":
        return name in target_metadata.tables
    return True


def run_migrations() -> None:
    with get_engine().connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_name=include_name,
            # Keep the bookkeeping table (alembic_version) in public, next to our tables.
            version_table_schema="public",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline mode is not set up. Run migrations against the database.")
run_migrations()
