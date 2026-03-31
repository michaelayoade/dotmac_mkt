"""007 – add post deliveries for cross-platform publishing

Revision ID: 007_post_deliveries
Revises: 006_meta_ads_provider
Create Date: 2026-03-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "007_post_deliveries"
down_revision = "006_meta_ads_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "CREATE TYPE postdeliverystatus AS ENUM "
            "('draft', 'planned', 'published', 'failed'); "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$"
        )
    )

    op.create_table(
        "post_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            postgresql.ENUM(
                "meta_instagram",
                "meta_facebook",
                "meta_ads",
                "twitter",
                "linkedin",
                "google_ads",
                "google_analytics",
                name="channelprovider",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("content_override", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft",
                "planned",
                "published",
                "failed",
                name="postdeliverystatus",
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("external_post_id", sa.String(200), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_post_delivery_post_id", "post_deliveries", ["post_id"])
    op.create_index("ix_post_delivery_channel_id", "post_deliveries", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_post_delivery_channel_id", table_name="post_deliveries")
    op.drop_index("ix_post_delivery_post_id", table_name="post_deliveries")
    op.drop_table("post_deliveries")
