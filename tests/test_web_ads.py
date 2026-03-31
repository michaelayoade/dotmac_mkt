"""Tests for the unified ads dashboard routes."""

from datetime import date
from decimal import Decimal

from app.models.ad_campaign import (
    Ad,
    AdCampaign,
    AdEntityStatus,
    AdGroup,
    AdMetric,
    AdPlatform,
)


def _seed_ad_data(db_session, channel):
    """Seed a simple ad hierarchy for testing."""
    ac = AdCampaign(
        channel_id=channel.id,
        platform=AdPlatform.meta,
        external_id="camp_test",
        name="Test Meta Campaign",
        status=AdEntityStatus.active,
    )
    db_session.add(ac)
    db_session.flush()

    ag = AdGroup(
        ad_campaign_id=ac.id,
        external_id="adset_test",
        name="Test Ad Set",
        status=AdEntityStatus.active,
    )
    db_session.add(ag)
    db_session.flush()

    ad = Ad(
        ad_group_id=ag.id,
        external_id="ad_test",
        name="Test Ad",
        status=AdEntityStatus.active,
    )
    db_session.add(ad)
    db_session.flush()

    metric = AdMetric(
        ad_id=ad.id,
        metric_date=date(2026, 3, 25),
        impressions=Decimal("5000"),
        clicks=Decimal("200"),
        spend=Decimal("50.00"),
        conversions=Decimal("5"),
    )
    db_session.add(metric)
    db_session.commit()

    return ac, ag, ad, metric


def test_ads_dashboard_renders(client, db_session, auth_token, channel):
    _seed_ad_data(db_session, channel)

    response = client.get(
        "/analytics/ads",
        cookies={"access_token": auth_token},
    )
    assert response.status_code == 200
    html = response.text
    assert "Ad Campaigns" in html
    assert "Test Meta Campaign" in html
    assert "Meta Ads" in html


def test_ads_dashboard_empty_state(client, auth_token):
    """With no seeded ad data, the dashboard shows the empty state."""
    response = client.get(
        "/analytics/ads?start_date=2020-01-01&end_date=2020-01-02",
        cookies={"access_token": auth_token},
    )
    assert response.status_code == 200
    html = response.text
    assert "No ad campaigns synced yet" in html


def test_ads_dashboard_platform_filter(client, db_session, auth_token, channel):
    _seed_ad_data(db_session, channel)

    # Filter to meta — should show the seeded campaign
    response = client.get(
        "/analytics/ads?platform=meta&start_date=2026-03-01&end_date=2026-03-31",
        cookies={"access_token": auth_token},
    )
    assert response.status_code == 200
    html = response.text
    assert "Test Meta Campaign" in html


def test_ad_campaign_detail_renders(client, db_session, auth_token, channel):
    ac, _, _, _ = _seed_ad_data(db_session, channel)

    response = client.get(
        f"/analytics/ads/{ac.id}",
        cookies={"access_token": auth_token},
    )
    assert response.status_code == 200
    html = response.text
    assert "Test Meta Campaign" in html
    assert "Test Ad Set" in html
    assert "Test Ad" in html


def test_ad_campaign_detail_not_found(client, db_session, auth_token):
    from uuid import uuid4

    response = client.get(
        f"/analytics/ads/{uuid4()}",
        cookies={"access_token": auth_token},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "error" in response.headers["location"]
