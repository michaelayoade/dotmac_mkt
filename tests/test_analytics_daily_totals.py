"""Tests for AnalyticsService.get_daily_totals()."""

from datetime import UTC, date, datetime, timedelta

from app.models.channel_metric import MetricType
from app.models.post import Post, PostStatus

from app.services.analytics_service import AnalyticsService


def test_get_daily_totals_returns_dict_per_date(db_session, channel):
    """get_daily_totals returns a list of dicts with date + metric sums."""
    svc = AnalyticsService(db_session)
    today = date.today()
    yesterday = today - timedelta(days=1)

    svc.upsert_metric(channel.id, today, MetricType.impressions, 100.0)
    svc.upsert_metric(channel.id, yesterday, MetricType.impressions, 50.0)
    svc.upsert_metric(channel.id, today, MetricType.clicks, 10.0)
    db_session.commit()

    result = svc.get_daily_totals(start_date=yesterday, end_date=today)

    assert len(result) == 2
    day_today = next(r for r in result if r["date"] == today.isoformat())
    assert day_today["impressions"] == 100
    assert day_today["clicks"] == 10

    day_yesterday = next(r for r in result if r["date"] == yesterday.isoformat())
    assert day_yesterday["impressions"] == 50


def test_get_daily_totals_empty_range(db_session):
    """Returns empty list when no data in range."""
    svc = AnalyticsService(db_session)
    today = date.today()
    result = svc.get_daily_totals(
        start_date=today - timedelta(days=90),
        end_date=today - timedelta(days=80),
    )
    assert result == []


def test_get_daily_totals_filters_by_post_and_metric_date(
    db_session, campaign, channel, person
):
    """get_daily_totals can be narrowed to one post on one day."""
    svc = AnalyticsService(db_session)
    today = date.today()
    yesterday = today - timedelta(days=1)

    post_a = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Post A",
        status=PostStatus.published,
        published_at=datetime.now(UTC),
        created_by=person.id,
    )
    post_b = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Post B",
        status=PostStatus.published,
        published_at=datetime.now(UTC),
        created_by=person.id,
    )
    db_session.add_all([post_a, post_b])
    db_session.flush()

    svc.upsert_metric(
        channel.id, yesterday, MetricType.impressions, 50.0, post_id=post_a.id
    )
    svc.upsert_metric(
        channel.id, today, MetricType.impressions, 100.0, post_id=post_a.id
    )
    svc.upsert_metric(
        channel.id, today, MetricType.impressions, 25.0, post_id=post_b.id
    )
    db_session.commit()

    result = svc.get_daily_totals(
        start_date=yesterday,
        end_date=today,
        post_id=post_a.id,
        metric_date=today,
    )

    assert result == [
        {
            "date": today.isoformat(),
            "impressions": 100,
            "reach": 0,
            "clicks": 0,
            "engagement": 0,
        }
    ]


def test_get_post_impression_rows_returns_per_post_per_day(
    db_session, campaign, channel, person
):
    svc = AnalyticsService(db_session)
    today = date.today()
    yesterday = today - timedelta(days=1)

    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Launch Post",
        status=PostStatus.published,
        published_at=datetime.now(UTC),
        created_by=person.id,
    )
    db_session.add(post)
    db_session.flush()

    svc.upsert_metric(
        channel.id, yesterday, MetricType.impressions, 40.0, post_id=post.id
    )
    svc.upsert_metric(
        channel.id, today, MetricType.impressions, 65.0, post_id=post.id
    )
    db_session.commit()

    rows = svc.get_post_impression_rows(start_date=yesterday, end_date=today)

    assert rows[0]["date"] == today.isoformat()
    assert rows[0]["post_title"] == "Launch Post"
    assert rows[0]["impressions"] == 65
    assert rows[1]["date"] == yesterday.isoformat()
