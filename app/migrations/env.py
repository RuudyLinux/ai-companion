import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models  # noqa: E402,F401  (registers every table on Base.metadata)
from database import Base, engine  # noqa: E402

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=engine.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:  # called programmatically with an open connection
        _run(connection)
        return
    with engine.connect() as conn:
        _run(conn)


def _run(connection) -> None:
    is_sqlite = connection.dialect.name == "sqlite"
    if is_sqlite:
        # Batch mode rebuilds tables (create copy, drop original, rename). With foreign keys
        # on, SQLite's DROP TABLE does an implicit DELETE that would CASCADE into child
        # tables and wipe real data, so enforcement is paused for the migration run.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        # end SQLAlchemy's autobegun transaction; otherwise Alembic sees an outer
        # transaction, never commits, and everything is rolled back on close
        connection.commit()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite can't ALTER most things; batch mode rebuilds tables instead
        render_as_batch=is_sqlite,
        compare_type=True,
    )
    try:
        with context.begin_transaction():
            context.run_migrations()
    finally:
        if is_sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
