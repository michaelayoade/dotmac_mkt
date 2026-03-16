"""005 – marketing domain tables

Revision ID: 005_marketing_tables
Revises: 004_notifications
Create Date: 2026-03-14
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "005_marketing_tables"
down_revision = "004_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # ── Pre-create enum types safely ──────────────────────
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE campaignstatus AS ENUM "
        "('draft', 'active', 'paused', 'completed', 'archived'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE campaignmemberrole AS ENUM ('owner', 'contributor'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE channelprovider AS ENUM "
        "('meta_instagram', 'meta_facebook', 'twitter', 'linkedin', "
        "'google_ads', 'google_analytics'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE channelstatus AS ENUM ('connected', 'disconnected', 'error'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE poststatus AS ENUM ('draft', 'planned'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE assettype AS ENUM "
        "('image', 'video', 'document', 'template', 'brand_guide'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE drivestatus AS ENUM ('active', 'missing', 'access_denied'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE taskstatus AS ENUM ('todo', 'in_progress', 'done'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE metrictype AS ENUM "
        "('impressions', 'reach', 'clicks', 'engagement', 'spend', "
        "'conversions', 'likes', 'shares', 'retweets', 'sessions', "
        "'pageviews', 'users', 'bounce_rate'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    ))

    # ── campaigns ────────────────────────────────────────
    if not inspector.has_table("campaigns"):
        op.create_table(
            "campaigns",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "draft",
                    "active",
                    "paused",
                    "completed",
                    "archived",
                    name="campaignstatus",
                    create_type=False,
                ),
                server_default="draft",
            ),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column(
                "created_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("people.id"),
                nullable=False,
            ),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )

    # ── channels ─────────────────────────────────────────
    if not inspector.has_table("channels"):
        op.create_table(
            "channels",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column(
                "provider",
                postgresql.ENUM(
                    "meta_instagram",
                    "meta_facebook",
                    "twitter",
                    "linkedin",
                    "google_ads",
                    "google_analytics",
                    name="channelprovider",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "connected",
                    "disconnected",
                    "error",
                    name="channelstatus",
                    create_type=False,
                ),
                server_default="disconnected",
            ),
            sa.Column("credentials_encrypted", sa.LargeBinary(), nullable=True),
            sa.Column("external_account_id", sa.String(200), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )

    # ── assets ───────────────────────────────────────────
    if not inspector.has_table("assets"):
        op.create_table(
            "assets",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column(
                "asset_type",
                postgresql.ENUM(
                    "image",
                    "video",
                    "document",
                    "template",
                    "brand_guide",
                    name="assettype",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column("drive_file_id", sa.String(200), nullable=True),
            sa.Column("drive_url", sa.Text(), nullable=True),
            sa.Column("thumbnail_url", sa.Text(), nullable=True),
            sa.Column("mime_type", sa.String(100), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("tags", postgresql.JSONB(), server_default="[]"),
            sa.Column(
                "drive_status",
                postgresql.ENUM(
                    "active",
                    "missing",
                    "access_denied",
                    name="drivestatus",
                    create_type=False,
                ),
                server_default="active",
            ),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "uploaded_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("people.id"),
                nullable=True,
            ),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )

    # ── posts ────────────────────────────────────────────
    if not inspector.has_table("posts"):
        op.create_table(
            "posts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "channel_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("channels.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "draft", "planned",
                    name="poststatus", create_type=False,
                ),
                server_default="draft",
            ),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("external_post_id", sa.String(200), nullable=True),
            sa.Column(
                "created_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("people.id"),
                nullable=False,
            ),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )
        op.create_index("ix_post_campaign_id", "posts", ["campaign_id"])
        op.create_index("ix_post_channel_id", "posts", ["channel_id"])

    # ── tasks ────────────────────────────────────────────
    if not inspector.has_table("tasks"):
        op.create_table(
            "tasks",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "todo", "in_progress", "done",
                    name="taskstatus", create_type=False,
                ),
                server_default="todo",
            ),
            sa.Column(
                "assignee_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("people.id"),
                nullable=True,
            ),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column(
                "created_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("people.id"),
                nullable=False,
            ),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )
        op.create_index("ix_task_campaign_id", "tasks", ["campaign_id"])

    # ── channel_metrics ──────────────────────────────────
    if not inspector.has_table("channel_metrics"):
        op.create_table(
            "channel_metrics",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "channel_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("channels.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "post_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("posts.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("metric_date", sa.Date(), nullable=False),
            sa.Column(
                "metric_type",
                postgresql.ENUM(
                    "impressions",
                    "reach",
                    "clicks",
                    "engagement",
                    "spend",
                    "conversions",
                    "likes",
                    "shares",
                    "retweets",
                    "sessions",
                    "pageviews",
                    "users",
                    "bounce_rate",
                    name="metrictype",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column("value", sa.Numeric(18, 6), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )
        # Partial unique index: post-level metrics
        op.create_index(
            "ix_channel_metric_post",
            "channel_metrics",
            ["channel_id", "post_id", "metric_date", "metric_type"],
            unique=True,
            postgresql_where=sa.text("post_id IS NOT NULL"),
        )
        # Partial unique index: channel-level metrics
        op.create_index(
            "ix_channel_metric_channel",
            "channel_metrics",
            ["channel_id", "metric_date", "metric_type"],
            unique=True,
            postgresql_where=sa.text("post_id IS NULL"),
        )

    # ── Join tables ──────────────────────────────────────
    if not inspector.has_table("post_assets"):
        op.create_table(
            "post_assets",
            sa.Column(
                "post_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("posts.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "asset_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("assets.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )

    if not inspector.has_table("campaign_assets"):
        op.create_table(
            "campaign_assets",
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "asset_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("assets.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("sort_order", sa.Integer(), server_default="0"),
        )

    if not inspector.has_table("campaign_members"):
        op.create_table(
            "campaign_members",
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "person_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("people.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "role",
                postgresql.ENUM(
                    "owner", "contributor",
                    name="campaignmemberrole", create_type=False,
                ),
                server_default="contributor",
            ),
        )


def downgrade() -> None:
    op.drop_table("campaign_members")
    op.drop_table("campaign_assets")
    op.drop_table("post_assets")
    op.drop_table("channel_metrics")
    op.drop_table("tasks")
    op.drop_table("posts")
    op.drop_table("assets")
    op.drop_table("channels")
    op.drop_table("campaigns")

    for enum_name in [
        "metrictype",
        "taskstatus",
        "drivestatus",
        "assettype",
        "poststatus",
        "channelstatus",
        "channelprovider",
        "campaignmemberrole",
        "campaignstatus",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
