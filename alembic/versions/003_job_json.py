"""Store the full normalized JobPosting payload on each job posting row.

The platform ``job_postings`` table is a flattened projection that drops
dashboard-facing fields (career_track, role_tags, classification_uncertain,
...). Keeping the validated pipeline payload alongside it lets the dashboard
read Postgres without widening the relational schema for every new field.

Existing rows are left NULL and fill in on their next refresh upsert; readers
filter on ``job_json IS NOT NULL``.

Revision ID: 003_job_json
Revises: 002_career_platform
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "003_job_json"
down_revision = "002_career_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("job_json", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("job_postings", "job_json")
