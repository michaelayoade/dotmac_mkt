"""Tests for marketing domain models (Campaign, Asset, Channel, Post, Task, ChannelMetric)."""

from datetime import UTC, date, datetime

from sqlalchemy import insert, select

from app.models.asset import Asset, AssetType, DriveStatus
from app.models.campaign import (
    Campaign,
    CampaignMemberRole,
    CampaignStatus,
    campaign_assets,
    campaign_members,
)
from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.models.channel_metric import ChannelMetric, MetricType
from app.models.post import Post, PostStatus
from app.models.task import Task, TaskStatus

# ────────────────────────── Campaign CRUD ──────────────────────────


class TestCampaignModel:
    def test_create_campaign(self, db_session, person):
        c = Campaign(
            name="Spring Launch",
            description="Spring product launch campaign",
            status=CampaignStatus.draft,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            created_by=person.id,
        )
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)

        assert c.id is not None
        assert c.name == "Spring Launch"
        assert c.status == CampaignStatus.draft
        assert c.created_by == person.id
        assert c.created_at is not None

    def test_read_campaign(self, db_session, campaign):
        fetched = db_session.get(Campaign, campaign.id)
        assert fetched is not None
        assert fetched.name == "Test Campaign"

    def test_update_campaign_status(self, db_session, campaign):
        campaign.status = CampaignStatus.active
        db_session.commit()
        db_session.refresh(campaign)
        assert campaign.status == CampaignStatus.active

    def test_list_campaigns(self, db_session, person):
        for i in range(3):
            db_session.add(
                Campaign(
                    name=f"Camp {i}",
                    status=CampaignStatus.draft,
                    created_by=person.id,
                )
            )
        db_session.commit()

        stmt = select(Campaign).where(Campaign.created_by == person.id)
        results = list(db_session.scalars(stmt).all())
        assert len(results) >= 3


# ──────────────── Campaign-Asset M2M ────────────────


class TestCampaignAssetM2M:
    def test_link_asset_to_campaign(self, db_session, campaign, asset):
        db_session.execute(
            insert(campaign_assets).values(
                campaign_id=campaign.id,
                asset_id=asset.id,
                sort_order=0,
            )
        )
        db_session.commit()
        db_session.refresh(campaign)

        assert len(campaign.assets) == 1
        assert campaign.assets[0].id == asset.id


# ──────────────── Campaign-Members M2M ────────────────


class TestCampaignMembersM2M:
    def test_add_person_as_member(self, db_session, campaign, person):
        db_session.execute(
            insert(campaign_members).values(
                campaign_id=campaign.id,
                person_id=person.id,
                role=CampaignMemberRole.contributor,
            )
        )
        db_session.commit()
        db_session.refresh(campaign)

        assert len(campaign.members) == 1
        assert campaign.members[0].id == person.id


# ────────────────────────── Channel CRUD ──────────────────────────


class TestChannelModel:
    def test_create_channel(self, db_session):
        ch = Channel(
            name="Company Facebook",
            provider=ChannelProvider.meta_facebook,
            status=ChannelStatus.disconnected,
            external_account_id="fb-page-123",
        )
        db_session.add(ch)
        db_session.commit()
        db_session.refresh(ch)

        assert ch.id is not None
        assert ch.provider == ChannelProvider.meta_facebook
        assert ch.status == ChannelStatus.disconnected

    def test_read_channel(self, db_session, channel):
        fetched = db_session.get(Channel, channel.id)
        assert fetched is not None
        assert fetched.name == "Test Instagram"
        assert fetched.provider == ChannelProvider.meta_instagram

    def test_update_channel_status(self, db_session, channel):
        channel.status = ChannelStatus.error
        db_session.commit()
        db_session.refresh(channel)
        assert channel.status == ChannelStatus.error

    def test_list_channels(self, db_session):
        for provider in [ChannelProvider.twitter, ChannelProvider.linkedin]:
            db_session.add(
                Channel(
                    name=f"Ch-{provider.value}",
                    provider=provider,
                    status=ChannelStatus.connected,
                )
            )
        db_session.commit()

        stmt = select(Channel)
        results = list(db_session.scalars(stmt).all())
        assert len(results) >= 2


# ────────────────────────── Post CRUD ──────────────────────────


class TestPostModel:
    def test_create_post(self, db_session, campaign, channel, person):
        p = Post(
            campaign_id=campaign.id,
            channel_id=channel.id,
            title="Launch Announcement",
            content="We are excited to announce...",
            status=PostStatus.draft,
            created_by=person.id,
        )
        db_session.add(p)
        db_session.commit()
        db_session.refresh(p)

        assert p.id is not None
        assert p.campaign_id == campaign.id
        assert p.channel_id == channel.id
        assert p.status == PostStatus.draft

    def test_post_planned_status(self, db_session, campaign, channel, person):
        p = Post(
            campaign_id=campaign.id,
            channel_id=channel.id,
            title="Scheduled Post",
            status=PostStatus.planned,
            scheduled_at=datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
            created_by=person.id,
        )
        db_session.add(p)
        db_session.commit()
        db_session.refresh(p)

        assert p.status == PostStatus.planned
        assert p.scheduled_at is not None

    def test_post_campaign_relationship(self, db_session, campaign, channel, person):
        p = Post(
            campaign_id=campaign.id,
            channel_id=channel.id,
            title="Relationship Test",
            created_by=person.id,
        )
        db_session.add(p)
        db_session.commit()
        db_session.refresh(p)

        assert p.campaign is not None
        assert p.campaign.id == campaign.id
        assert p.channel is not None
        assert p.channel.id == channel.id


# ────────────────────────── Task CRUD ──────────────────────────


class TestTaskModel:
    def test_create_task(self, db_session, campaign, person):
        t = Task(
            campaign_id=campaign.id,
            title="Design banner",
            description="Create hero banner for campaign",
            status=TaskStatus.todo,
            assignee_id=person.id,
            due_date=date(2026, 4, 10),
            created_by=person.id,
        )
        db_session.add(t)
        db_session.commit()
        db_session.refresh(t)

        assert t.id is not None
        assert t.campaign_id == campaign.id
        assert t.status == TaskStatus.todo
        assert t.assignee_id == person.id

    def test_update_task_status(self, db_session, campaign, person):
        t = Task(
            campaign_id=campaign.id,
            title="Review copy",
            created_by=person.id,
        )
        db_session.add(t)
        db_session.commit()

        t.status = TaskStatus.in_progress
        db_session.commit()
        db_session.refresh(t)
        assert t.status == TaskStatus.in_progress

        t.status = TaskStatus.done
        db_session.commit()
        db_session.refresh(t)
        assert t.status == TaskStatus.done

    def test_task_campaign_relationship(self, db_session, campaign, person):
        t = Task(
            campaign_id=campaign.id,
            title="Check analytics",
            created_by=person.id,
        )
        db_session.add(t)
        db_session.commit()
        db_session.refresh(t)

        assert t.campaign is not None
        assert t.campaign.id == campaign.id


# ────────────────────────── Asset CRUD ──────────────────────────


class TestAssetModel:
    def test_create_asset(self, db_session):
        a = Asset(
            name="promo-video.mp4",
            asset_type=AssetType.video,
            drive_file_id="vid-456",
            drive_url="https://drive.google.com/file/d/vid-456",
            mime_type="video/mp4",
            file_size=50_000_000,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)

        assert a.id is not None
        assert a.asset_type == AssetType.video
        assert a.drive_status == DriveStatus.active

    def test_read_asset(self, db_session, asset):
        fetched = db_session.get(Asset, asset.id)
        assert fetched is not None
        assert fetched.name == "hero-banner.png"
        assert fetched.mime_type == "image/png"

    def test_asset_types(self, db_session):
        for at in [AssetType.document, AssetType.template, AssetType.brand_guide]:
            a = Asset(name=f"file-{at.value}", asset_type=at)
            db_session.add(a)
        db_session.commit()

        stmt = select(Asset).where(Asset.asset_type == AssetType.document)
        results = list(db_session.scalars(stmt).all())
        assert len(results) >= 1


# ──────────────── ChannelMetric Creation ────────────────


class TestChannelMetricModel:
    def test_create_metric(self, db_session, channel):
        m = ChannelMetric(
            channel_id=channel.id,
            metric_date=date(2026, 3, 12),
            metric_type=MetricType.impressions,
            value=15000,
        )
        db_session.add(m)
        db_session.commit()
        db_session.refresh(m)

        assert m.id is not None
        assert m.channel_id == channel.id
        assert m.metric_type == MetricType.impressions
        assert float(m.value) == 15000.0

    def test_create_post_level_metric(self, db_session, campaign, channel, person):
        p = Post(
            campaign_id=campaign.id,
            channel_id=channel.id,
            title="Metric Post",
            created_by=person.id,
        )
        db_session.add(p)
        db_session.commit()
        db_session.refresh(p)

        m = ChannelMetric(
            channel_id=channel.id,
            post_id=p.id,
            metric_date=date(2026, 3, 12),
            metric_type=MetricType.clicks,
            value=342,
        )
        db_session.add(m)
        db_session.commit()
        db_session.refresh(m)

        assert m.post_id == p.id
        assert m.metric_type == MetricType.clicks

    def test_metric_types(self, db_session, channel):
        for mt in MetricType:
            m = ChannelMetric(
                channel_id=channel.id,
                metric_date=date(2026, 3, 13),
                metric_type=mt,
                value=100,
            )
            db_session.add(m)
        db_session.commit()

        stmt = select(ChannelMetric).where(ChannelMetric.channel_id == channel.id)
        results = list(db_session.scalars(stmt).all())
        assert len(results) >= len(MetricType)
