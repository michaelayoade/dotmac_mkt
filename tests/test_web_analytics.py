import re
from datetime import UTC, date, datetime, timedelta

from starlette.requests import Request

from app.models.channel import ChannelProvider, ChannelStatus
from app.models.channel_metric import MetricType
from app.models.post import Post, PostStatus
from app.schemas.channel import ChannelCreate
from app.services.analytics_service import AnalyticsService
from app.services.channel_service import ChannelService
from app.services.credential_service import CredentialService
from app.web.analytics import analytics_overview


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/analytics",
            "headers": [],
            "query_string": b"",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "http_version": "1.1",
            "root_path": "",
            "app": None,
            "state": {},
        }
    )


def test_analytics_overview_supports_post_and_day_filters(
    db_session, campaign, channel, person
):
    today = date.today()
    yesterday = today - timedelta(days=1)
    analytics = AnalyticsService(db_session)

    post_a = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Launch Post A",
        status=PostStatus.published,
        published_at=datetime.now(UTC),
        created_by=person.id,
    )
    post_b = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Launch Post B",
        status=PostStatus.published,
        published_at=datetime.now(UTC),
        created_by=person.id,
    )
    db_session.add_all([post_a, post_b])
    db_session.flush()

    analytics.upsert_metric(
        channel.id, yesterday, MetricType.impressions, 40.0, post_id=post_a.id
    )
    analytics.upsert_metric(
        channel.id, today, MetricType.impressions, 60.0, post_id=post_a.id
    )
    analytics.upsert_metric(
        channel.id, today, MetricType.reach, 25.0, post_id=post_b.id
    )
    db_session.commit()

    response = analytics_overview(
        _request(),
        start_date=yesterday.isoformat(),
        end_date=today.isoformat(),
        metric_date=today.isoformat(),
        post_id=str(post_a.id),
        db=db_session,
        auth={},
    )

    assert response.status_code == 200
    html = response.body.decode()
    assert "Post Impressions" in html
    assert f"Showing impressions for {today.isoformat()}" in html
    assert "Filtered to post: Launch Post A" in html
    assert f'value="{post_a.id}" selected' in html

    match = re.search(r"<p[^>]*>([0-9,]+)</p>\s*<p[^>]*>Total Impressions</p>", html)
    assert match is not None
    assert match.group(1) == "60"


def test_analytics_overview_falls_back_to_channel_level_when_post_has_no_metrics(
    db_session, campaign, channel, person
):
    today = date.today()
    week_ago = today - timedelta(days=7)
    analytics = AnalyticsService(db_session)

    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Launch Post Without Metrics",
        status=PostStatus.published,
        published_at=datetime.now(UTC),
        created_by=person.id,
    )
    db_session.add(post)
    db_session.flush()

    analytics.upsert_metric(channel.id, week_ago, MetricType.reach, 125.0)
    analytics.upsert_metric(channel.id, today, MetricType.engagement, 45.0)
    db_session.commit()

    response = analytics_overview(
        _request(),
        start_date=week_ago.isoformat(),
        end_date=today.isoformat(),
        post_id=str(post.id),
        db=db_session,
        auth={},
    )

    assert response.status_code == 200
    html = response.body.decode()
    assert "Metrics Over Time" in html
    assert "Reach" in html
    assert "Engagement" in html
    assert week_ago.isoformat() in html
    assert today.isoformat() in html
    assert ">125<" in html
    assert ">45<" in html


def test_meta_ads_page_renders_history_rows(
    client, db_session, person, auth_session, auth_token, monkeypatch
):
    import sys

    from cryptography.fernet import Fernet

    mock_cfg = sys.modules["app.config"]
    monkeypatch.setattr(
        mock_cfg.settings, "encryption_key", Fernet.generate_key().decode()
    )

    channel = ChannelService(db_session).create(
        ChannelCreate(name="Meta Ads Account", provider=ChannelProvider.meta_ads)
    )
    channel.status = ChannelStatus.connected
    channel.external_account_id = "9876543210"
    channel.credentials_encrypted = CredentialService().encrypt(
        {"access_token": "meta-access", "account_id": "9876543210"}
    )
    db_session.commit()

    async def _fake_fetch_ads_history(self, start_date, end_date, *, limit=250):
        return [
            {
                "campaign_name": "Spring Launch",
                "adset_name": "Warm Audience",
                "ad_name": "Creative A",
                "date_start": start_date.isoformat(),
                "date_stop": end_date.isoformat(),
                "impressions": 1200.0,
                "reach": 900.0,
                "clicks": 54.0,
                "spend": 87.65,
                "ctr": 4.5,
                "cpc": 1.62,
                "cpp": 0.1,
                "conversions": 8.0,
            }
        ]

    monkeypatch.setattr(
        "app.adapters.meta_ads.MetaAdsAdapter.fetch_ads_history",
        _fake_fetch_ads_history,
    )

    response = client.get(
        "/analytics/meta-ads",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert "Meta Ads History" in html
    assert "Spring Launch" in html
    assert "Creative A" in html
    assert "87.65" in html
