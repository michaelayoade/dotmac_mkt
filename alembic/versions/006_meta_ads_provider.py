"""006 – add Meta Ads channel provider

Revision ID: 006_meta_ads_provider
Revises: 005_marketing_tables
Create Date: 2026-03-26
"""

import sqlalchemy as sa

from alembic import op

revision = "006_meta_ads_provider"
down_revision = "005_marketing_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TYPE channelprovider ADD VALUE IF NOT EXISTS 'meta_ads'"))


def downgrade() -> None:
    pass
