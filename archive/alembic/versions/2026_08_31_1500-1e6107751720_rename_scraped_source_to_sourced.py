"""rename 'scraped' TranscriptVersion.source to 'sourced'

Revision ID: 1e6107751720
Revises: c5d0e3a7f9b1
Create Date: 2026-08-31 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "1e6107751720"
down_revision: Union[str, Sequence[str], None] = "c5d0e3a7f9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Data-only, no schema change -- `transcript_versions.source` is a
    plain String(20), not an enum, so no ALTER is needed to hold the new
    value.

    Renames the ingest-default provenance/display token from "scraped"
    to "sourced" (Ryan's call, 2026-08-31 -- "we should never say
    scraped, always sourced"; see BACKLOG_DONE.md for the full rename,
    including the ~20 code sites this migration's twin PR updates). Per
    this repo's own convention ("do it as its own change, with the data
    update and the code sites in one deploy, or not at all"), this must
    land in the same deploy as that code -- render.yaml's
    preDeployCommand runs this before the new build starts serving, so
    every row is already "sourced" by the time the renamed
    _SOURCE_LABELS/default code goes live.
    """
    op.execute(
        "UPDATE transcript_versions SET source = 'sourced' WHERE source = 'scraped'"
    )


def downgrade() -> None:
    """Reverses the rename. Symmetric with upgrade() -- safe as long as
    no row has legitimately picked up a new, different "sourced" value
    from something other than this migration's own backfill, which
    isn't distinguishable after the fact. Acceptable: this is the same
    class of one-way-in-practice downgrade as every other data backfill
    in this directory (see a6556277a68d's last_alerted_at for the
    precedent)."""
    op.execute(
        "UPDATE transcript_versions SET source = 'scraped' WHERE source = 'sourced'"
    )
