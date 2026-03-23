import re
from datetime import UTC, date, datetime, timedelta

from app.models.channel_metric import MetricType
from app.models.post import Post, PostStatus
from app.services.analytics_service import AnalyticsService


def test_analytics_overview_supports_post_and_day_filters(
    client, auth_token, db_session, campaign, channel, person
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
        channel.id, today, MetricType.impressions, 25.0, post_id=post_b.id
    )
    db_session.commit()

    client.cookies.set("access_token", auth_token)
    response = client.get(
        f"/analytics?start_date={yesterday.isoformat()}&end_date={today.isoformat()}"
        f"&metric_date={today.isoformat()}&post_id={post_a.id}"
    )

    assert response.status_code == 200
    html = response.text
    assert "Post Impressions" in html
    assert f"Showing impressions for {today.isoformat()}" in html
    assert "Filtered to post: Launch Post A" in html
    assert f'value="{post_a.id}" selected' in html

    match = re.search(r"Total Impressions</p>\s*<p[^>]*>([0-9,]+)</p>", html)
    assert match is not None
    assert match.group(1) == "60"


def test_analytics_overview_falls_back_to_channel_level_when_post_has_no_metrics(
    client, auth_token, db_session, campaign, channel, person
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

    client.cookies.set("access_token", auth_token)
    response = client.get(
        f"/analytics?start_date={week_ago.isoformat()}&end_date={today.isoformat()}"
        f"&post_id={post.id}"
    )

    assert response.status_code == 200
    html = response.text
    assert "Metrics Over Time" in html
    assert "Peak: 125" in html
    assert "Reach" in html
    assert "Engagement" in html
