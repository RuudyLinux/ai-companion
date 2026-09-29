"""
Programmatic Alembic runner. Production should run `alembic upgrade head` as a deploy
step (AUTO_MIGRATE defaults to off there); development and tests call
`upgrade_database()` on startup so a fresh checkout just works.

Databases created before Alembic existed (tables present, no alembic_version) are
stamped at the baseline revision first, so their data is migrated, not recreated.
"""

import logging

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from core.config import APP_DIR
from database import engine

log = logging.getLogger("app.migrations")

BASELINE_REVISION = "0001_baseline"


def alembic_config() -> Config:
    config = Config(str(APP_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(APP_DIR / "migrations"))
    config.attributes["configure_logging"] = False
    return config


def upgrade_database() -> None:
    config = alembic_config()
    tables = set(inspect(engine).get_table_names())
    if "users" in tables and "alembic_version" not in tables:
        log.info("pre-Alembic database detected; stamping baseline revision")
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")
