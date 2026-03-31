import importlib
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.adapters.base import MetricData, PostData
from app.models.campaign import Campaign, CampaignStatus
from app.models.channel import ChannelProvider
from app.models.channel_metric import ChannelMetric, MetricType
from app.models.post import Post, PostStatus
from app.models.post_delivery import PostDelivery, PostDeliveryStatus
from app.services.analytics_service import AnalyticsService
from app.tasks.analytics_sync import _sync_channel

analytics_sync_module = importlib.import_module("app.tasks.analytics_sync")


class _FakeCreds:
    def decrypt(self, _payload):
        return {"access_token": "token", "account_id": "acct-1"}


class _FakeAdapter:
    def __init__(self, metrics, posts=None):
        self._metrics = metrics
        self._posts = posts or []

    async def fetch_analytics(self, start_date, end_date):
        assert start_date <= end_date
        return self._metrics

    async def fetch_posts(self, since=None):
        return self._posts


class _InvalidManualTokenAdapter:
    async def validate_connection(self):
        return False

    async def refresh_token(self, _value):
        raise AssertionError("manual access-token-only credentials should not refresh")


def test_sync_channel_maps_external_post_id_to_local_post(
    db_session, campaign, channel, person, monkeypatch
):
    channel.provider = ChannelProvider.twitter
    channel.credentials_encrypted = b"encrypted"

    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Launch Tweet",
        status=PostStatus.published,
        external_post_id="tweet-123",
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()

    metrics = [
        MetricData(
            metric_date=date(2026, 3, 24),
            metric_type="impressions",
            value=55.0,
            post_id="tweet-123",
        )
    ]
    monkeypatch.setattr(
        analytics_sync_module,
        "get_adapter",
        lambda provider, **kwargs: _FakeAdapter(metrics),
    )

    analytics = AnalyticsService(db_session)
    _sync_channel(
        channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24)
    )
    db_session.commit()

    row = db_session.execute(
        select(ChannelMetric).where(
            ChannelMetric.channel_id == channel.id,
            ChannelMetric.metric_date == date(2026, 3, 24),
            ChannelMetric.metric_type == MetricType.impressions,
        )
    ).scalar_one()
    assert row.metric_type == MetricType.impressions
    assert row.post_id == post.id

    impression_rows = analytics.get_post_impression_rows(
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 24),
        post_id=post.id,
    )
    assert impression_rows == [
        {
            "date": "2026-03-24",
            "post_id": str(post.id),
            "post_title": "Launch Tweet",
            "channel_name": channel.name,
            "impressions": 55,
        }
    ]


def test_sync_channel_matches_remote_posts_before_mapping_metrics(
    db_session, campaign, channel, person, monkeypatch
):
    channel.provider = ChannelProvider.twitter
    channel.credentials_encrypted = b"encrypted"

    published_at = datetime(2026, 3, 24, 12, 0, tzinfo=UTC)
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Launch Tweet",
        content="Ship the launch thread",
        status=PostStatus.published,
        published_at=published_at,
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()

    metrics = [
        MetricData(
            metric_date=date(2026, 3, 24),
            metric_type="impressions",
            value=55.0,
            post_id="tweet-123",
        )
    ]
    remote_posts = [
        PostData(
            external_id="tweet-123",
            title="",
            content="Ship the launch thread",
            published_at=published_at,
        )
    ]
    monkeypatch.setattr(
        analytics_sync_module,
        "get_adapter",
        lambda provider, **kwargs: _FakeAdapter(metrics, remote_posts),
    )

    analytics = AnalyticsService(db_session)
    _sync_channel(
        channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24)
    )
    db_session.commit()
    db_session.refresh(post)

    assert post.external_post_id == "tweet-123"
    row = db_session.execute(
        select(ChannelMetric).where(
            ChannelMetric.channel_id == channel.id,
            ChannelMetric.metric_date == date(2026, 3, 24),
            ChannelMetric.metric_type == MetricType.impressions,
        )
    ).scalar_one()
    assert row.post_id == post.id


def test_sync_channel_keeps_unmapped_external_post_metrics_at_channel_level(
    db_session, channel, monkeypatch
):
    channel.provider = ChannelProvider.twitter
    channel.credentials_encrypted = b"encrypted"
    db_session.commit()

    metrics = [
        MetricData(
            metric_date=date(2026, 3, 24),
            metric_type="impressions",
            value=80.0,
            post_id="missing-post",
        )
    ]
    monkeypatch.setattr(
        analytics_sync_module,
        "get_adapter",
        lambda provider, **kwargs: _FakeAdapter(metrics),
    )

    analytics = AnalyticsService(db_session)
    _sync_channel(
        channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24)
    )
    db_session.commit()

    row = db_session.execute(
        select(ChannelMetric).where(
            ChannelMetric.channel_id == channel.id,
            ChannelMetric.metric_date == date(2026, 3, 24),
            ChannelMetric.metric_type == MetricType.impressions,
        )
    ).scalar_one()
    assert row.post_id is None

    channel_metrics = analytics.get_channel_metrics(
        channel.id,
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 24),
    )
    assert len(channel_metrics) == 1
    assert float(channel_metrics[0].value) == 80.0
    channel_post_metrics = (
        db_session.execute(
            select(ChannelMetric).where(
                ChannelMetric.channel_id == channel.id,
                ChannelMetric.post_id.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    assert channel_post_metrics == []


def test_sync_channel_imports_remote_post_when_no_local_match(
    db_session, campaign, channel, monkeypatch
):
    channel.provider = ChannelProvider.meta_instagram
    channel.credentials_encrypted = b"encrypted"
    db_session.commit()

    published_at = datetime(2026, 3, 24, 12, 0, tzinfo=UTC)
    metrics = [
        MetricData(
            metric_date=date(2026, 3, 24),
            metric_type="impressions",
            value=82.0,
            post_id="ig-123",
        )
    ]
    remote_posts = [
        PostData(
            external_id="ig-123",
            title="",
            content="Fresh Instagram post from the native app",
            published_at=published_at,
        )
    ]
    monkeypatch.setattr(
        analytics_sync_module,
        "get_adapter",
        lambda provider, **kwargs: _FakeAdapter(metrics, remote_posts),
    )

    analytics = AnalyticsService(db_session)
    _sync_channel(
        channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24)
    )
    db_session.commit()

    imported_post = db_session.scalar(
        select(Post).where(Post.external_post_id == "ig-123")
    )
    assert imported_post is not None
    assert imported_post.campaign_id == campaign.id
    assert imported_post.channel_id == channel.id
    assert imported_post.status == PostStatus.published
    assert imported_post.title == "Fresh Instagram post from the native app"
    delivery = db_session.scalar(
        select(PostDelivery).where(
            PostDelivery.post_id == imported_post.id,
            PostDelivery.channel_id == channel.id,
        )
    )
    assert delivery is not None
    assert delivery.status == PostDeliveryStatus.published
    assert delivery.external_post_id == "ig-123"

    row = db_session.execute(
        select(ChannelMetric).where(
            ChannelMetric.channel_id == channel.id,
            ChannelMetric.metric_date == date(2026, 3, 24),
            ChannelMetric.metric_type == MetricType.impressions,
        )
    ).scalar_one()
    assert row.post_id == imported_post.id


def test_sync_channel_import_prefers_campaign_matching_publish_window(
    db_session, campaign, channel, person, monkeypatch
):
    channel.provider = ChannelProvider.meta_instagram
    channel.credentials_encrypted = b"encrypted"

    campaign.status = CampaignStatus.completed
    campaign.start_date = date(2026, 3, 1)
    campaign.end_date = date(2026, 3, 10)

    matching_campaign = Campaign(
        name="Spring Launch",
        status=CampaignStatus.active,
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 31),
        created_by=person.id,
    )
    db_session.add(matching_campaign)
    db_session.commit()

    published_at = datetime(2026, 3, 24, 12, 0, tzinfo=UTC)
    remote_posts = [
        PostData(
            external_id="ig-456",
            title="",
            content="Spring launch reel",
            published_at=published_at,
        )
    ]
    monkeypatch.setattr(
        analytics_sync_module,
        "get_adapter",
        lambda provider, **kwargs: _FakeAdapter([], remote_posts),
    )

    analytics = AnalyticsService(db_session)
    _sync_channel(
        channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24)
    )
    db_session.commit()

    imported_post = db_session.scalar(
        select(Post).where(Post.external_post_id == "ig-456")
    )
    assert imported_post is not None
    assert imported_post.campaign_id == matching_campaign.id


def test_sync_channel_import_prefers_campaign_already_linked_to_channel(
    db_session, campaign, channel, person, monkeypatch
):
    channel.provider = ChannelProvider.meta_instagram
    channel.credentials_encrypted = b"encrypted"

    campaign.status = CampaignStatus.active
    campaign.start_date = date(2026, 3, 20)
    campaign.end_date = date(2026, 3, 31)
    existing_post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Existing Instagram Plan",
        status=PostStatus.draft,
        created_by=person.id,
    )

    other_campaign = Campaign(
        name="Parallel Launch",
        status=CampaignStatus.active,
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 31),
        created_by=person.id,
    )
    db_session.add_all([existing_post, other_campaign])
    db_session.commit()

    published_at = datetime(2026, 3, 24, 12, 0, tzinfo=UTC)
    remote_posts = [
        PostData(
            external_id="ig-789",
            title="",
            content="Imported reel should land in linked campaign",
            published_at=published_at,
        )
    ]
    monkeypatch.setattr(
        analytics_sync_module,
        "get_adapter",
        lambda provider, **kwargs: _FakeAdapter([], remote_posts),
    )

    analytics = AnalyticsService(db_session)
    _sync_channel(
        channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24)
    )
    db_session.commit()

    imported_post = db_session.scalar(
        select(Post).where(Post.external_post_id == "ig-789")
    )
    assert imported_post is not None
    assert imported_post.campaign_id == campaign.id


def test_build_live_adapter_skips_refresh_for_manual_access_token_only(
    db_session, channel, monkeypatch
):
    channel.provider = ChannelProvider.meta_facebook

    monkeypatch.setattr(
        analytics_sync_module,
        "get_adapter",
        lambda provider, **kwargs: _InvalidManualTokenAdapter(),
    )

    with pytest.raises(
        RuntimeError, match="manual access tokens are not auto-refreshed"
    ):
        import asyncio

        asyncio.run(
            analytics_sync_module._build_live_adapter(
                channel,
                {
                    "access_token": "token",
                    "account_id": "acct-1",
                    "manual_token": True,
                },
                _FakeCreds(),
                db_session,
            )
        )


def test_sync_channel_removes_missing_single_target_facebook_posts(
    db_session, campaign, channel, person, monkeypatch
):
    channel.provider = ChannelProvider.meta_facebook
    channel.credentials_encrypted = b"encrypted"

    removed_post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Removed on Facebook",
        content="Gone remotely",
        status=PostStatus.published,
        external_post_id="fb-missing",
        created_by=person.id,
    )
    kept_post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Still on Facebook",
        content="Still remote",
        status=PostStatus.published,
        external_post_id="fb-keep",
        created_by=person.id,
    )
    db_session.add_all([removed_post, kept_post])
    db_session.commit()

    monkeypatch.setattr(
        analytics_sync_module,
        "get_adapter",
        lambda provider, **kwargs: _FakeAdapter(
            [],
            [PostData(external_id="fb-keep", title="", content="", published_at=None)],
        ),
    )

    analytics = AnalyticsService(db_session)
    _sync_channel(
        channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24)
    )
    db_session.commit()

    assert db_session.get(Post, removed_post.id) is None
    assert db_session.get(Post, kept_post.id) is not None


def test_sync_channel_removes_missing_single_delivery_facebook_posts(
    db_session, campaign, channel, person, monkeypatch
):
    channel.provider = ChannelProvider.meta_facebook
    channel.credentials_encrypted = b"encrypted"

    post = Post(
        campaign_id=campaign.id,
        channel_id=None,
        title="Delivery-backed Facebook Post",
        content="Gone remotely",
        status=PostStatus.published,
        external_post_id=None,
        created_by=person.id,
    )
    db_session.add(post)
    db_session.flush()
    db_session.add(
        PostDelivery(
            post_id=post.id,
            channel_id=channel.id,
            provider=channel.provider,
            status=PostDeliveryStatus.published,
            external_post_id="fb-delivery-missing",
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        analytics_sync_module,
        "get_adapter",
        lambda provider, **kwargs: _FakeAdapter(
            [],
            [PostData(external_id="fb-other", title="", content="", published_at=None)],
        ),
    )

    analytics = AnalyticsService(db_session)
    _sync_channel(
        channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24)
    )
    db_session.commit()

    assert db_session.get(Post, post.id) is None
