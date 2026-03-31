"""Tests for AdSyncService — upsert logic with mock adapter data."""

from decimal import Decimal

from app.models.ad_campaign import (
    Ad,
    AdCampaign,
    AdEntityStatus,
    AdGroup,
    AdMetric,
    AdPlatform,
)
from app.services.ad_sync_service import AdSyncService


def test_sync_meta_rows_creates_hierarchy(db_session, channel):
    """Meta Ads flat rows create ad_campaign → ad_group → ad → metric."""
    rows = [
        {
            "campaign_id": "camp_001",
            "campaign_name": "Spring Sale",
            "adset_id": "adset_001",
            "adset_name": "Lookalike 1%",
            "ad_id": "ad_001",
            "ad_name": "Carousel A",
            "date_start": "2026-03-20",
            "impressions": 5000,
            "reach": 3000,
            "clicks": 120,
            "spend": 45.50,
            "conversions": 3,
            "ctr": 2.4,
            "cpc": 0.38,
        },
        {
            "campaign_id": "camp_001",
            "campaign_name": "Spring Sale",
            "adset_id": "adset_001",
            "adset_name": "Lookalike 1%",
            "ad_id": "ad_002",
            "ad_name": "Video B",
            "date_start": "2026-03-20",
            "impressions": 3000,
            "reach": 2000,
            "clicks": 80,
            "spend": 30.25,
            "conversions": 1,
            "ctr": 2.67,
            "cpc": 0.38,
        },
    ]

    svc = AdSyncService(db_session)
    count = svc.sync_platform_rows(channel.id, AdPlatform.meta, rows)
    db_session.commit()

    assert count == 2

    # One campaign created
    from sqlalchemy import select

    campaigns = list(db_session.scalars(select(AdCampaign)).all())
    assert len(campaigns) == 1
    assert campaigns[0].external_id == "camp_001"
    assert campaigns[0].name == "Spring Sale"
    assert campaigns[0].platform == AdPlatform.meta
    assert campaigns[0].status == AdEntityStatus.active

    # One ad group
    groups = list(db_session.scalars(select(AdGroup)).all())
    assert len(groups) == 1
    assert groups[0].external_id == "adset_001"
    assert groups[0].name == "Lookalike 1%"

    # Two ads
    ads = list(db_session.scalars(select(Ad)).all())
    assert len(ads) == 2
    ad_names = {a.name for a in ads}
    assert ad_names == {"Carousel A", "Video B"}

    # Two metric rows
    metrics = list(db_session.scalars(select(AdMetric)).all())
    assert len(metrics) == 2
    total_spend = sum(float(m.spend) for m in metrics)
    assert abs(total_spend - 75.75) < 0.01


def test_sync_google_rows_creates_hierarchy(db_session, channel):
    """Google Ads flat rows use different field names but produce same hierarchy."""
    rows = [
        {
            "campaign_id": "g_camp_001",
            "campaign_name": "Search - Brand",
            "ad_group_id": "g_ag_001",
            "ad_group_name": "Exact Match",
            "ad_id": "g_ad_001",
            "ad_name": "RSA 1",
            "date_start": "2026-03-21",
            "impressions": 8000,
            "clicks": 400,
            "spend": 120.00,
            "conversions": 10,
            "ctr": 5.0,
            "average_cpc": 0.30,
        },
    ]

    svc = AdSyncService(db_session)
    count = svc.sync_platform_rows(channel.id, AdPlatform.google, rows)
    db_session.commit()

    assert count == 1

    from sqlalchemy import select

    campaigns = list(
        db_session.scalars(
            select(AdCampaign).where(AdCampaign.platform == AdPlatform.google)
        ).all()
    )
    assert len(campaigns) == 1
    assert campaigns[0].name == "Search - Brand"
    assert campaigns[0].platform == AdPlatform.google


def test_sync_linkedin_rows_maps_fields_correctly(db_session, channel):
    """LinkedIn uses campaign_group_id/campaign_id/creative_id field naming."""
    rows = [
        {
            "campaign_group_id": "li_cg_001",
            "campaign_group_name": "Q1 Awareness",
            "campaign_id": "li_camp_001",
            "campaign_name": "Sponsored Content",
            "creative_id": "li_cr_001",
            "creative_name": "Creative li_cr_001",
            "date_start": "2026-03-22",
            "impressions": 2000,
            "clicks": 50,
            "spend": 25.00,
            "conversions": 2,
        },
    ]

    svc = AdSyncService(db_session)
    count = svc.sync_platform_rows(channel.id, AdPlatform.linkedin, rows)
    db_session.commit()

    assert count == 1

    from sqlalchemy import select

    # LinkedIn campaign_group → ad_campaigns
    campaigns = list(
        db_session.scalars(
            select(AdCampaign).where(AdCampaign.platform == AdPlatform.linkedin)
        ).all()
    )
    assert len(campaigns) == 1
    assert campaigns[0].external_id == "li_cg_001"
    assert campaigns[0].name == "Q1 Awareness"

    # LinkedIn campaign → ad_groups
    groups = list(
        db_session.scalars(
            select(AdGroup).where(AdGroup.ad_campaign_id == campaigns[0].id)
        ).all()
    )
    assert len(groups) == 1
    assert groups[0].external_id == "li_camp_001"

    # LinkedIn creative → ads
    ads = list(
        db_session.scalars(select(Ad).where(Ad.ad_group_id == groups[0].id)).all()
    )
    assert len(ads) == 1
    assert ads[0].external_id == "li_cr_001"


def test_sync_upserts_existing_records(db_session, channel):
    """Second sync with updated names and metrics upserts, not duplicates."""
    rows_v1 = [
        {
            "campaign_id": "camp_99",
            "campaign_name": "Old Name",
            "adset_id": "adset_99",
            "adset_name": "Set A",
            "ad_id": "ad_99",
            "ad_name": "Ad A",
            "date_start": "2026-03-20",
            "impressions": 100,
            "clicks": 10,
            "spend": 5.0,
            "conversions": 0,
        },
    ]
    rows_v2 = [
        {
            "campaign_id": "camp_99",
            "campaign_name": "New Name",
            "adset_id": "adset_99",
            "adset_name": "Set A",
            "ad_id": "ad_99",
            "ad_name": "Ad A",
            "date_start": "2026-03-20",
            "impressions": 200,
            "clicks": 20,
            "spend": 10.0,
            "conversions": 1,
        },
    ]

    svc = AdSyncService(db_session)
    svc.sync_platform_rows(channel.id, AdPlatform.meta, rows_v1)
    db_session.flush()
    svc.sync_platform_rows(channel.id, AdPlatform.meta, rows_v2)
    db_session.commit()

    from sqlalchemy import select

    campaigns = list(
        db_session.scalars(
            select(AdCampaign).where(AdCampaign.external_id == "camp_99")
        ).all()
    )
    assert len(campaigns) == 1
    assert campaigns[0].name == "New Name"

    ad_campaign_ids = [c.id for c in campaigns]
    groups = list(
        db_session.scalars(
            select(AdGroup).where(AdGroup.ad_campaign_id.in_(ad_campaign_ids))
        ).all()
    )
    ad_ids = [
        a.id
        for g in groups
        for a in db_session.scalars(select(Ad).where(Ad.ad_group_id == g.id)).all()
    ]
    metrics = list(
        db_session.scalars(select(AdMetric).where(AdMetric.ad_id.in_(ad_ids))).all()
    )
    assert len(metrics) == 1
    assert float(metrics[0].impressions) == 200
    assert float(metrics[0].spend) == Decimal("10")
