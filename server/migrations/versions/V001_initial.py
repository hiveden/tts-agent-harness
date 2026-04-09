"""V001 initial — business schema (ADR-001 §5.1)

Revision ID: V001_initial
Revises:
Create Date: 2026-04-09

This migration is the **contract** defined in ADR-001 §5.1. Field names,
types, and constraints are reproduced verbatim. Any change to the business
schema must ship as a NEW migration; never edit this file.

Tables:
  - episodes
  - chunks
  - takes
  - stage_runs
  - events            (+ pg_notify trigger on INSERT)
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "V001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------
    # episodes
    # -------------------------------------------------------------------
    op.create_table(
        "episodes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("script_uri", sa.Text(), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "archived_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # -------------------------------------------------------------------
    # chunks
    # -------------------------------------------------------------------
    op.create_table(
        "chunks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "episode_id",
            sa.Text(),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("shot_id", sa.Text(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_normalized", sa.Text(), nullable=False),
        sa.Column("subtitle_text", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("selected_take_id", sa.Text(), nullable=True),
        sa.Column("boundary_hash", sa.Text(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column(
            "last_edited_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("episode_id", "shot_id", "idx", name="chunks_episode_shot_idx_key"),
    )

    # -------------------------------------------------------------------
    # takes
    # -------------------------------------------------------------------
    op.create_table(
        "takes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "chunk_id",
            sa.Text(),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("audio_uri", sa.Text(), nullable=False),
        sa.Column("duration_s", sa.REAL(), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # -------------------------------------------------------------------
    # stage_runs
    # -------------------------------------------------------------------
    op.create_table(
        "stage_runs",
        sa.Column(
            "chunk_id",
            sa.Text(),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("log_uri", sa.Text(), nullable=True),
        sa.Column("prefect_task_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "stale",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.PrimaryKeyConstraint("chunk_id", "stage", name="stage_runs_pkey"),
    )

    # -------------------------------------------------------------------
    # events
    # -------------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("episode_id", sa.Text(), nullable=False),
        sa.Column("chunk_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "events_episode_idx",
        "events",
        ["episode_id", sa.text("id DESC")],
    )

    # -------------------------------------------------------------------
    # pg_notify trigger on events INSERT
    #
    # ADR-001 §5.1 contract: payload must include at least {ep, id}.
    # FastAPI SSE handler (A9-API) will LISTEN 'episode_events' and reverse
    # lookup the full row by id.
    # -------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_episode_event() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify(
                'episode_events',
                json_build_object('ep', NEW.episode_id, 'id', NEW.id)::text
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE TRIGGER events_notify_trigger
        AFTER INSERT ON events
        FOR EACH ROW
        EXECUTE FUNCTION notify_episode_event();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS events_notify_trigger ON events;")
    op.execute("DROP FUNCTION IF EXISTS notify_episode_event();")
    op.drop_index("events_episode_idx", table_name="events")
    op.drop_table("events")
    op.drop_table("stage_runs")
    op.drop_table("takes")
    op.drop_table("chunks")
    op.drop_table("episodes")
