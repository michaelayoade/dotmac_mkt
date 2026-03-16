"""Tests for AnalyticsService.get_daily_totals()."""

from datetime import date, timedelta

from app.models.channel_metric import MetricType
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
