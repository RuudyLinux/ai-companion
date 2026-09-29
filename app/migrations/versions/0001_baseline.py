"""Baseline: the schema as it existed before Alembic (created by Base.metadata.create_all
plus scripts/add_voice_adaptive_columns.py). Existing databases are stamped at this
revision automatically (see core/migrations.py) instead of running it.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("emotion_tracking_enabled", sa.Boolean(), nullable=False),
        sa.Column("default_voice_id", sa.String(36), nullable=True),
        sa.Column("default_language", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("voice_speed", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("voice_volume_db", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("voice_emotional_intensity", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("voice_style", sa.String(), nullable=False, server_default="casual"),
        sa.Column("voice_auto_adaptive", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "voices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("speaker_ref", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("preview_audio_path", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    # users <-> voices reference each other; add this side once both tables exist
    with op.batch_alter_table("users") as batch:
        batch.create_foreign_key("fk_users_default_voice_id", "voices", ["default_voice_id"], ["id"])

    op.create_table(
        "companions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("persona_prompt", sa.Text(), nullable=False),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("voice_id", sa.String(36), sa.ForeignKey("voices.id"), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "emotional_memory",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("recent_emotions", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("companion_id", sa.String(36), sa.ForeignKey("companions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("emotion", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "voice_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True
        ),
        sa.Column("audio_path", sa.String(), nullable=False),
        sa.Column("voice_id", sa.String(36), sa.ForeignKey("voices.id"), nullable=True),
        sa.Column("tts_style", sa.String(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    for table in ("voice_messages", "messages", "conversations", "emotional_memory", "companions"):
        op.drop_table(table)
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("fk_users_default_voice_id", type_="foreignkey")
    op.drop_table("voices")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
