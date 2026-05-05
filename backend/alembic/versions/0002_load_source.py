"""add `source` column to load_requests (customer | broker)

Revision ID: 0002_load_source
Revises: 0001_initial_schema
Create Date: 2026-05-04

Adds a nullable `source` column to load_requests so the fleet optimiser can
distinguish direct-customer freight from broker-aggregated spot freight.
Backfills existing rows with `customer` (the seeded book of business is all
relationship-based), then leaves the column nullable so future loads can be
unclassified before they're triaged.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_load_source"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "load_requests",
        sa.Column("source", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_load_requests_source", "load_requests", ["source"], unique=False,
    )
    # Backfill: every existing row is a direct-customer load.
    op.execute("UPDATE load_requests SET source = 'customer' WHERE source IS NULL")


def downgrade() -> None:
    op.drop_index("ix_load_requests_source", table_name="load_requests")
    op.drop_column("load_requests", "source")
