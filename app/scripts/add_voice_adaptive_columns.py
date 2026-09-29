"""
Adds per-user adaptive-voice preference columns. No Alembic in this project — schema
changes are one-off scripts (see scripts/promote_admin.py). SQLite supports ADD COLUMN
directly; idempotent via PRAGMA table_info.

Usage: venv\\Scripts\\python.exe scripts\\add_voice_adaptive_columns.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from database import engine

COLUMNS = [
    ("voice_speed", "FLOAT NOT NULL DEFAULT 1.0"),
    ("voice_volume_db", "FLOAT NOT NULL DEFAULT 0.0"),
    ("voice_emotional_intensity", "FLOAT NOT NULL DEFAULT 1.0"),
    ("voice_style", "VARCHAR NOT NULL DEFAULT 'casual'"),
    ("voice_auto_adaptive", "BOOLEAN NOT NULL DEFAULT 1"),
]


def main():
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        for name, ddl_type in COLUMNS:
            if name in existing:
                print(f"users.{name} already exists — skipping")
                continue
            conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl_type}"))
            print(f"Added users.{name}")


if __name__ == "__main__":
    main()
