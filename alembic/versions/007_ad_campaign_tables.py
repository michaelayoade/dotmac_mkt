"""007 – ad campaign tracking tables

Revision ID: 007_ad_campaign_tables
Revises: 006_meta_ads_provider
Create Date: 2026-03-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "007_ad_campaign_tables"
down_revision = "006_meta_ads_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Add linkedin_ads to channelprovider enum
    op.execute(
        sa.text("ALTER TYPE channelprovider ADD VALUE IF NOT EXISTS 'linkedin_ads'")
    )

    # Create new enum types safely
    op.execute(
        sa.text("""
            DO $$ BEGIN
                CREATE TYPE adplatform AS ENUM ('meta', 'google', 'linkedin');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
        """)
    )
    op.execute(
        sa.text("""
            DO $$ BEGIN
                CREATE TYPE adentitystatus AS ENUM ('active', 'paused', 'removed', 'unknown');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
        """)
    )

    # ad_campaigns
    if not inspector.has_table("ad_campaigns"):
        op.create_table(
            "ad_campaigns",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "channel_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("channels.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "platform",
                postgresql.ENUM("meta", "google", "linkedin", name="adplatform", create_type=False),
                nullable=False,
            ),
            sa.Column("external_id", sa.String(200), nullable=False),
            sa.Column("name", sa.String(500), nullable=False),
            sa.Column(
                "status",
                postgresql.ENUM("active", "paused", "removed", "unknown", name="adentitystatus", create_type=False),
                server_default="unknown",
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("channel_id", "platform", "external_id", name="uq_ad_campaign_channel_platform_ext"),
        )
        op.create_index("ix_ad_campaign_channel_id", "ad_campaigns", ["channel_id"])
        op.create_index("ix_ad_campaign_campaign_id", "ad_campaigns", ["campaign_id"])

    # ad_groups
    if not inspector.has_table("ad_groups"):
        op.create_table(
            "ad_groups",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "ad_campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("ad_campaigns.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("external_id", sa.String(200), nullable=False),
            sa.Column("name", sa.String(500), nullable=False),
            sa.Column(
                "status",
                postgresql.ENUM("active", "paused", "removed", "unknown", name="adentitystatus", create_type=False),
                server_default="unknown",
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("ad_campaign_id", "external_id", name="uq_ad_group_campaign_ext"),
        )
        op.create_index("ix_ad_group_ad_campaign_id", "ad_groups", ["ad_campaign_id"])

    # ads
    if not inspector.has_table("ads"):
        op.create_table(
            "ads",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "ad_group_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("ad_groups.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("external_id", sa.String(200), nullable=False),
            sa.Column("name", sa.String(500), nullable=False),
            sa.Column(
                "status",
                postgresql.ENUM("active", "paused", "removed", "unknown", name="adentitystatus", create_type=False),
                server_default="unknown",
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("ad_group_id", "external_id", name="uq_ad_group_ext"),
        )
        op.create_index("ix_ad_ad_group_id", "ads", ["ad_group_id"])

    # ad_metrics
    if not inspector.has_table("ad_metrics"):
        op.create_table(
            "ad_metrics",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "ad_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("ads.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("metric_date", sa.Date, nullable=False),
            sa.Column("impressions", sa.Numeric(18, 6), server_default="0"),
            sa.Column("reach", sa.Numeric(18, 6), server_default="0"),
            sa.Column("clicks", sa.Numeric(18, 6), server_default="0"),
            sa.Column("spend", sa.Numeric(18, 6), server_default="0"),
            sa.Column("conversions", sa.Numeric(18, 6), server_default="0"),
            sa.Column("ctr", sa.Numeric(10, 6), server_default="0"),
            sa.Column("cpc", sa.Numeric(18, 6), server_default="0"),
            sa.Column("currency_code", sa.String(10), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("ad_id", "metric_date", name="uq_ad_metric_ad_date"),
        )
        op.create_index("ix_ad_metric_date", "ad_metrics", ["metric_date"])


def downgrade() -> None:
    op.drop_table("ad_metrics")
    op.drop_table("ads")
    op.drop_table("ad_groups")
    op.drop_table("ad_campaigns")
    op.execute("DROP TYPE IF EXISTS adentitystatus")
    op.execute("DROP TYPE IF EXISTS adplatform")
