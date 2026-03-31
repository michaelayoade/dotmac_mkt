import importlib
from datetime import UTC, datetime
from datetime import date

import pytest
from sqlalchemy import select

from app.adapters.base import MetricData, PostData
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
    _sync_channel(channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24))
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
    _sync_channel(channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24))
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
    _sync_channel(channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24))
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
    channel_post_metrics = db_session.execute(
        select(ChannelMetric).where(
            ChannelMetric.channel_id == channel.id,
            ChannelMetric.post_id.is_not(None),
        )
    ).scalars().all()
    assert channel_post_metrics == []


def test_build_live_adapter_skips_refresh_for_manual_access_token_only(
    db_session, channel, monkeypatch
):
    channel.provider = ChannelProvider.meta_facebook

    monkeypatch.setattr(
        analytics_sync_module,
        "get_adapter",
        lambda provider, **kwargs: _InvalidManualTokenAdapter(),
    )

    with pytest.raises(RuntimeError, match="manual access tokens are not auto-refreshed"):
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
    _sync_channel(channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24))
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
    _sync_channel(channel, _FakeCreds(), analytics, date(2026, 3, 20), date(2026, 3, 24))
    db_session.commit()

    assert db_session.get(Post, post.id) is None
