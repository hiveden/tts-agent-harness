"""V004 — add FK + CASCADE on events.episode_id and events.chunk_id

Revision ID: V004_events_fk_cascade
Revises: V003_episode_locked
Create Date: 2026-04-21

Changes:
  - Clean up orphan rows left over from the previous schema (no FK enforced):
      * events with episode_id not matching any episodes.id
      * events with chunk_id not matching any chunks.id
  - Add ForeignKey(episodes.id, ON DELETE CASCADE) on events.episode_id
  - Add ForeignKey(chunks.id,   ON DELETE CASCADE) on events.chunk_id

Rationale:
  Previously, Event.episode_id / chunk_id were bare TEXT columns without
  foreign-key enforcement. Deleting an Episode (or Chunk) left dangling
  Event rows. This migration adds the missing constraints so that cascade
  deletes propagate all the way through the audit log.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "V004_events_fk_cascade"
down_revision: Union[str, None] = "V003_episode_locked"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Drop orphan rows so the new FK does not fail on existing data.
    op.execute(
        "DELETE FROM events "
        "WHERE episode_id NOT IN (SELECT id FROM episodes)"
    )
    op.execute(
        "DELETE FROM events "
        "WHERE chunk_id IS NOT NULL "
        "AND chunk_id NOT IN (SELECT id FROM chunks)"
    )

    # 2) Add FK constraints with ON DELETE CASCADE.
    op.create_foreign_key(
        "events_episode_id_fkey",
        source_table="events",
        referent_table="episodes",
        local_cols=["episode_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "events_chunk_id_fkey",
        source_table="events",
        referent_table="chunks",
        local_cols=["chunk_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("events_chunk_id_fkey", "events", type_="foreignkey")
    op.drop_constraint("events_episode_id_fkey", "events", type_="foreignkey")
