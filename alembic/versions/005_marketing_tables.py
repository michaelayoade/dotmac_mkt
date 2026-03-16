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

    # ── Enums ────────────────────────────────────────────
    campaignstatus = postgresql.ENUM(
        "draft",
        "active",
        "paused",
        "completed",
        "archived",
        name="campaignstatus",
        create_type=False,
    )
    campaignstatus.create(conn, checkfirst=True)

    campaignmemberrole = postgresql.ENUM(
        "owner",
        "contributor",
        name="campaignmemberrole",
        create_type=False,
    )
    campaignmemberrole.create(conn, checkfirst=True)

    channelprovider = postgresql.ENUM(
        "meta_instagram",
        "meta_facebook",
        "twitter",
        "linkedin",
        "google_ads",
        "google_analytics",
        name="channelprovider",
        create_type=False,
    )
    channelprovider.create(conn, checkfirst=True)

    channelstatus = postgresql.ENUM(
        "connected",
        "disconnected",
        "error",
        name="channelstatus",
        create_type=False,
    )
    channelstatus.create(conn, checkfirst=True)

    poststatus = postgresql.ENUM(
        "draft",
        "planned",
        name="poststatus",
        create_type=False,
    )
    poststatus.create(conn, checkfirst=True)

    assettype = postgresql.ENUM(
        "image",
        "video",
        "document",
        "template",
        "brand_guide",
        name="assettype",
        create_type=False,
    )
    assettype.create(conn, checkfirst=True)

    drivestatus = postgresql.ENUM(
        "active",
        "missing",
        "access_denied",
        name="drivestatus",
        create_type=False,
    )
    drivestatus.create(conn, checkfirst=True)

    taskstatus = postgresql.ENUM(
        "todo",
        "in_progress",
        "done",
        name="taskstatus",
        create_type=False,
    )
    taskstatus.create(conn, checkfirst=True)

    metrictype = postgresql.ENUM(
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
    )
    metrictype.create(conn, checkfirst=True)

    # ── campaigns ────────────────────────────────────────
    if not inspector.has_table("campaigns"):
        op.create_table(
            "campaigns",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.Enum(
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
                sa.Enum(
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
                sa.Enum(
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
                sa.Enum(
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
                sa.Enum(
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
                sa.Enum("draft", "planned", name="poststatus", create_type=False),
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
                sa.Enum(
                    "todo", "in_progress", "done", name="taskstatus", create_type=False
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
                sa.Enum(
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
                sa.Enum(
                    "owner", "contributor", name="campaignmemberrole", create_type=False
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
