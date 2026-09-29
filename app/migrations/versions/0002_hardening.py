"""Hardening: sessions, memories, jobs, audit log, message states, voice ownership
metadata, privacy settings, indexes; converts legacy absolute file paths.

Revision ID: 0002_hardening
Revises: 0001_baseline
Create Date: 2026-09-30
"""

import ntpath
import posixpath

import sqlalchemy as sa
from alembic import op

revision = "0002_hardening"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)

LEGACY_TIMESTAMPS = {
    "users": ["created_at"],
    "voices": ["created_at"],
    "companions": ["created_at"],
    "emotional_memory": ["updated_at"],
    "conversations": ["created_at", "updated_at"],
    "messages": ["created_at"],
    "voice_messages": ["created_at"],
}


def _current_voice_engine() -> str:
    try:
        from core.config import settings

        return settings.voice_engine
    except Exception:
        return "xtts"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # ---------------------------------------------------------------- new tables
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("revoked_at", TZ, nullable=True),
        sa.Column("last_seen_at", TZ, nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    op.create_table(
        "memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("companion_id", sa.String(36), sa.ForeignKey("companions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", TZ, nullable=True),
        sa.Column("updated_at", TZ, nullable=True),
        sa.Column("expires_at", TZ, nullable=True),
        sa.Column("last_used_at", TZ, nullable=True),
    )
    op.create_index("ix_memories_user_type", "memories", ["user_id", "type"])
    op.create_index("ix_memories_user_expires", "memories", ["user_id", "expires_at"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("queue", sa.String(20), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=True),
        sa.Column("locked_by", sa.String(100), nullable=True),
        sa.Column("run_after", TZ, nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("started_at", TZ, nullable=True),
        sa.Column("finished_at", TZ, nullable=True),
    )
    op.create_index("ix_jobs_queue_status_run_after", "jobs", ["queue", "status", "run_after"])
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index("ix_jobs_dedupe_key", "jobs", ["dedupe_key"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_email", sa.String(320), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_type", "target_id"])

    # ---------------------------------------------------------------- users
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("store_voice_audio", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("data_retention_days", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("updated_at", TZ, nullable=True))
    # normalise emails, skipping any that would collide with another account's
    op.execute(
        "UPDATE users SET email = LOWER(TRIM(email)) WHERE NOT EXISTS ("
        "SELECT 1 FROM users other WHERE other.id <> users.id AND LOWER(TRIM(other.email)) = LOWER(TRIM(users.email)))"
    )

    # ---------------------------------------------------------------- companions
    op.execute("UPDATE companions SET is_public = false WHERE is_public IS NULL")
    with op.batch_alter_table("companions") as batch:
        batch.alter_column("is_public", existing_type=sa.Boolean(), nullable=False)
        batch.create_index("ix_companions_owner_id", ["owner_id"])
        batch.create_index("ix_companions_public_created", ["is_public", "created_at"])

    # ---------------------------------------------------------------- voices
    with op.batch_alter_table("voices") as batch:
        batch.add_column(sa.Column("provider", sa.String(20), nullable=False, server_default="xtts"))
        batch.add_column(sa.Column("provider_voice_id", sa.String(255), nullable=True))
        batch.add_column(sa.Column("clone_reference", sa.String(255), nullable=True))
        batch.add_column(sa.Column("language", sa.String(16), nullable=True))
        batch.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="active"))
        batch.add_column(sa.Column("consent_confirmed_at", TZ, nullable=True))
        batch.add_column(sa.Column("updated_at", TZ, nullable=True))
        batch.create_index("ix_voices_owner_id", ["owner_id"])

    # set-based so `alembic upgrade --sql` can render it for review
    op.execute(
        sa.text("UPDATE voices SET provider = :engine, provider_voice_id = speaker_ref").bindparams(
            engine=_current_voice_engine()
        )
    )
    # cloned voices seeded from a local file keep that file as their reference;
    # scripts/import_voice_reference.py re-homes it under DATA_DIR
    op.execute(
        "UPDATE voices SET provider = 'xtts', clone_reference = speaker_ref, provider_voice_id = NULL "
        "WHERE kind = 'cloned' AND (speaker_ref LIKE '%/%' OR speaker_ref LIKE '%\\%' ESCAPE '!' "
        "OR LOWER(speaker_ref) LIKE '%.wav' OR LOWER(speaker_ref) LIKE '%.mp3')"
    )
    # legacy cloned voices were seeded with no owner, which made them visible to every
    # user; give them to the first super_admin (or, failing that, the first user)
    op.execute(
        "UPDATE voices SET owner_id = (SELECT id FROM users ORDER BY "
        "CASE role WHEN 'super_admin' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, created_at LIMIT 1) "
        "WHERE kind = 'cloned' AND owner_id IS NULL"
    )
    op.execute("UPDATE voices SET status = 'disabled' WHERE kind = 'cloned' AND owner_id IS NULL")

    with op.batch_alter_table("voices") as batch:
        batch.drop_column("speaker_ref")

    # ---------------------------------------------------------------- conversations
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("summarized_until", TZ, nullable=True))
        batch.create_index("ix_conversations_companion_id", ["companion_id"])
        batch.create_index("ix_conversations_user_archived_updated", ["user_id", "archived", "updated_at"])

    # ---------------------------------------------------------------- messages
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("status", sa.String(16), nullable=False, server_default="completed"))
        batch.add_column(sa.Column("error_code", sa.String(64), nullable=True))
        batch.add_column(sa.Column("emotion_confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("response_strategy", sa.String(32), nullable=True))
        batch.add_column(sa.Column("model", sa.String(120), nullable=True))
        batch.add_column(sa.Column("updated_at", TZ, nullable=True))
        batch.create_index("ix_messages_conversation_created", ["conversation_id", "created_at"])
    # the old code stored this placeholder instead of recording the failure
    op.execute(
        "UPDATE messages SET status = 'failed', error_code = 'LEGACY_EMPTY_REPLY', content = '' "
        "WHERE role = 'assistant' AND (content = '' OR content = '[no reply generated]')"
    )

    # ---------------------------------------------------------------- voice_messages
    with op.batch_alter_table("voice_messages") as batch:
        batch.create_index("ix_voice_messages_voice_id", ["voice_id"])
        batch.create_index("ix_voice_messages_created_at", ["created_at"])
    # absolute paths (from whatever machine generated them) -> DATA_DIR-relative keys
    vm = sa.table("voice_messages", sa.column("id", sa.String), sa.column("audio_path", sa.String))
    rows = [] if op.get_context().as_sql else bind.execute(sa.select(vm.c.id, vm.c.audio_path)).all()
    for vm_id, path in rows:
        if path and (posixpath.isabs(path) or ntpath.isabs(path)):
            name = ntpath.basename(path) if "\\" in path else posixpath.basename(path)
            bind.execute(sa.update(vm).where(vm.c.id == vm_id).values(audio_path=f"voice_audio/{name}"))

    # ---------------------------------------------------------------- timestamps
    if is_pg:  # SQLite has no timezone-aware type; PostgreSQL should store timestamptz
        for table, columns in LEGACY_TIMESTAMPS.items():
            for column in columns:
                op.alter_column(
                    table,
                    column,
                    type_=TZ,
                    existing_type=sa.DateTime(),
                    postgresql_using=f"{column} AT TIME ZONE 'UTC'",
                )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table, columns in LEGACY_TIMESTAMPS.items():
            for column in columns:
                op.alter_column(table, column, type_=sa.DateTime(), existing_type=TZ)

    with op.batch_alter_table("voice_messages") as batch:
        batch.drop_index("ix_voice_messages_created_at")
        batch.drop_index("ix_voice_messages_voice_id")

    with op.batch_alter_table("messages") as batch:
        batch.drop_index("ix_messages_conversation_created")
        for column in ("updated_at", "model", "response_strategy", "emotion_confidence", "error_code", "status"):
            batch.drop_column(column)

    with op.batch_alter_table("conversations") as batch:
        batch.drop_index("ix_conversations_user_archived_updated")
        batch.drop_index("ix_conversations_companion_id")
        batch.drop_column("summarized_until")
        batch.drop_column("summary")

    with op.batch_alter_table("voices") as batch:
        batch.add_column(sa.Column("speaker_ref", sa.String(), nullable=False, server_default=""))
    op.execute("UPDATE voices SET speaker_ref = COALESCE(provider_voice_id, clone_reference, '')")
    with op.batch_alter_table("voices") as batch:
        batch.drop_index("ix_voices_owner_id")
        for column in (
            "updated_at", "consent_confirmed_at", "status", "language", "clone_reference", "provider_voice_id", "provider"
        ):
            batch.drop_column(column)

    with op.batch_alter_table("companions") as batch:
        batch.drop_index("ix_companions_public_created")
        batch.drop_index("ix_companions_owner_id")
        batch.alter_column("is_public", existing_type=sa.Boolean(), nullable=True)

    with op.batch_alter_table("users") as batch:
        for column in ("updated_at", "data_retention_days", "store_voice_audio", "memory_enabled"):
            batch.drop_column(column)

    for table in ("audit_logs", "jobs", "memories", "user_sessions"):
        op.drop_table(table)
