"""008 – merge marketing migration heads

Revision ID: 008_merge_marketing_heads
Revises: 007_ad_campaign_tables, 007_post_deliveries
Create Date: 2026-03-31
"""

from alembic import op

revision = "008_merge_marketing_heads"
down_revision = ("007_ad_campaign_tables", "007_post_deliveries")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
