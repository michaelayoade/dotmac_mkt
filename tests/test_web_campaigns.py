from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import app.web.campaigns as campaigns_web
from app.models.channel import ChannelProvider
from app.models.channel_metric import MetricType
from app.models.post import Post, PostStatus
from app.models.post_delivery import PostDelivery, PostDeliveryStatus
from app.services.analytics_service import AnalyticsService


def _csrf_token(client) -> str:
    """Get a valid CSRF token from the test client."""
    resp = client.get("/health")
    return resp.cookies.get("csrf_token", "")


def test_campaign_posts_tab_renders_split_view_with_post_metrics(
    client, db_session, auth_token, campaign, channel, person
):
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Launch Reel",
        content="Detailed caption for the launch reel.",
        status=PostStatus.published,
        scheduled_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
        external_post_id="meta-post-001",
        created_by=person.id,
    )
    db_session.add(post)
    db_session.flush()

    analytics = AnalyticsService(db_session)
    today = date.today()
    analytics.upsert_metric(
        channel.id, today - timedelta(days=1), MetricType.impressions, 120.0, post.id
    )
    analytics.upsert_metric(channel.id, today, MetricType.reach, 75.0, post.id)
    analytics.upsert_metric(channel.id, today, MetricType.engagement, 18.0, post.id)
    db_session.commit()

    response = client.get(
        f"/campaigns/{campaign.id}/tab/posts",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert "Organic Content" in html
    assert "Post Detail" in html
    assert "Launch Reel" in html
    assert "120" in html
    assert "75" in html
    assert "18" in html
    assert f"/campaigns/{campaign.id}/posts/{post.id}/detail" in html


def test_campaign_list_renders_post_inspector_for_recent_posts(
    client, db_session, auth_token, campaign, channel, person
):
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Homepage Launch Post",
        content="Inspector content on campaigns index.",
        status=PostStatus.published,
        created_by=person.id,
    )
    db_session.add(post)
    db_session.flush()

    analytics = AnalyticsService(db_session)
    today = date.today()
    analytics.upsert_metric(channel.id, today, MetricType.impressions, 310.0, post.id)
    analytics.upsert_metric(channel.id, today, MetricType.reach, 125.0, post.id)
    analytics.upsert_metric(channel.id, today, MetricType.engagement, 41.0, post.id)
    db_session.commit()

    response = client.get(
        "/campaigns",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert "Campaigns" in html
    assert "Homepage Launch Post" in html
    assert 'id="campaign-post-inspector"' in html
    assert "Post Detail" in html
    assert "Campaign: Test Campaign" in html
    assert "Inspector content on campaigns index." in html
    assert "310" in html
    assert "125" in html
    assert "41" in html
    assert f"/campaigns/{campaign.id}/posts/{post.id}/detail" in html


def test_campaign_list_live_sync_can_surface_recent_imported_instagram_post(
    client, db_session, auth_token, campaign, channel, person, monkeypatch
):
    channel.provider = ChannelProvider.meta_instagram
    db_session.commit()

    def _fake_live_sync(db):
        post = Post(
            campaign_id=campaign.id,
            channel_id=channel.id,
            title="Imported IG Reel",
            content="Synced from Instagram during page load.",
            status=PostStatus.published,
            external_post_id="ig-live-001",
            published_at=datetime.now(UTC),
            created_by=person.id,
        )
        db.add(post)
        db.flush()
        return 1

    monkeypatch.setattr(campaigns_web, "sync_recent_channel_posts_now", _fake_live_sync)

    response = client.get(
        "/campaigns",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert "Imported IG Reel" in html
    assert "Synced from Instagram during page load." in html


def test_campaign_post_detail_fragment_returns_selected_post_metrics(
    client, db_session, auth_token, campaign, channel, person
):
    first_post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Launch Teaser",
        status=PostStatus.published,
        created_by=person.id,
    )
    second_post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Launch Recap",
        content="Recap copy",
        status=PostStatus.published,
        external_post_id="meta-post-002",
        created_by=person.id,
    )
    db_session.add_all([first_post, second_post])
    db_session.flush()

    analytics = AnalyticsService(db_session)
    today = date.today()
    analytics.upsert_metric(
        channel.id, today, MetricType.impressions, 250.0, second_post.id
    )
    analytics.upsert_metric(channel.id, today, MetricType.reach, 90.0, second_post.id)
    analytics.upsert_metric(
        channel.id, today, MetricType.engagement, 33.0, second_post.id
    )
    db_session.commit()

    response = client.get(
        f"/campaigns/{campaign.id}/posts/{second_post.id}/detail",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert "Launch Recap" in html
    assert "Recap copy" in html
    assert "meta-post-002" in html
    assert "250" in html
    assert "90" in html
    assert "33" in html


def test_campaign_post_detail_fragment_shows_delivery_backed_external_links(
    client, db_session, auth_token, campaign, channel, person
):
    post = Post(
        campaign_id=campaign.id,
        channel_id=None,
        title="Delivery Synced Post",
        content="Imported from channel sync",
        status=PostStatus.published,
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
            external_post_id="ig-delivery-789",
            published_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    response = client.get(
        f"/campaigns/{campaign.id}/posts/{post.id}/detail",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert "External Links" in html
    assert "Test Instagram:" in html
    assert "ig-delivery-789" in html


def test_campaign_list_shows_edit_delete_actions_for_supported_published_posts(
    client, db_session, auth_token, campaign, channel, person
):
    channel.provider = ChannelProvider.twitter
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Editable Published Post",
        content="Already live.",
        status=PostStatus.published,
        external_post_id="tweet-123",
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()

    response = client.get(
        "/campaigns",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert f"/campaigns/{campaign.id}/posts/{post.id}/edit" in html
    assert f"/campaigns/{campaign.id}/posts/{post.id}/delete" in html


def test_campaign_posts_tab_shows_edit_delete_actions_for_supported_published_posts(
    client, db_session, auth_token, campaign, channel, person
):
    channel.provider = ChannelProvider.twitter
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Published Tab Post",
        content="Live content",
        status=PostStatus.published,
        external_post_id="tweet-456",
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()

    response = client.get(
        f"/campaigns/{campaign.id}/tab/posts",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert f"/campaigns/{campaign.id}/posts/{post.id}/edit" in html
    assert f"/campaigns/{campaign.id}/posts/{post.id}/delete" in html


def test_campaign_list_shows_edit_delete_actions_for_published_facebook_posts(
    client, db_session, auth_token, campaign, channel, person
):
    channel.provider = ChannelProvider.meta_facebook
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Facebook Published Post",
        content="Already on Facebook.",
        status=PostStatus.published,
        external_post_id="fb-post-123",
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()

    response = client.get(
        "/campaigns",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert f"/campaigns/{campaign.id}/posts/{post.id}/edit" in html
    assert f"/campaigns/{campaign.id}/posts/{post.id}/delete" in html


def test_campaign_posts_tab_shows_edit_delete_actions_for_published_facebook_posts(
    client, db_session, auth_token, campaign, channel, person
):
    channel.provider = ChannelProvider.meta_facebook
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Facebook Tab Post",
        content="Live on Facebook",
        status=PostStatus.published,
        external_post_id="fb-post-456",
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()

    response = client.get(
        f"/campaigns/{campaign.id}/tab/posts",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert f"/campaigns/{campaign.id}/posts/{post.id}/edit" in html
    assert f"/campaigns/{campaign.id}/posts/{post.id}/delete" in html


def test_campaign_posts_tab_shows_actions_for_single_delivery_published_facebook_post(
    client, db_session, auth_token, campaign, channel, person
):
    channel.provider = ChannelProvider.meta_facebook
    post = Post(
        campaign_id=campaign.id,
        channel_id=None,
        title="Delivery-backed Facebook Post",
        content="Live via delivery",
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
            external_post_id="fb-delivery-123",
        )
    )
    db_session.commit()

    response = client.get(
        f"/campaigns/{campaign.id}/tab/posts",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert "Test Instagram" in html
    assert f"/campaigns/{campaign.id}/posts/{post.id}/edit" in html
    assert f"/campaigns/{campaign.id}/posts/{post.id}/delete" in html


def test_campaign_list_prefers_recently_published_delivery_backed_posts_in_preview(
    client, db_session, auth_token, campaign, channel, person
):
    channel.provider = ChannelProvider.meta_facebook
    recent_post = Post(
        campaign_id=campaign.id,
        channel_id=None,
        title="Recent Facebook Publish",
        content="Just published",
        status=PostStatus.published,
        published_at=datetime.now(UTC),
        created_at=datetime.now(UTC) - timedelta(days=10),
        created_by=person.id,
    )
    older_drafts = [
        Post(
            campaign_id=campaign.id,
            channel_id=channel.id,
            title=f"Draft Post {idx}",
            status=PostStatus.draft,
            created_at=datetime.now(UTC) - timedelta(days=idx),
            created_by=person.id,
        )
        for idx in range(1, 4)
    ]
    db_session.add(recent_post)
    db_session.add_all(older_drafts)
    db_session.flush()
    db_session.add(
        PostDelivery(
            post_id=recent_post.id,
            channel_id=channel.id,
            provider=channel.provider,
            status=PostDeliveryStatus.published,
            external_post_id="fb-recent-123",
            published_at=recent_post.published_at,
        )
    )
    db_session.commit()

    response = client.get(
        "/campaigns",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert "Recent Facebook Publish" in html
    assert "Test Instagram" in html


# ── Post CRUD tests ──────────────────────────────────────────────────────────


def test_create_post_form_renders(client, db_session, auth_token, campaign, channel):
    response = client.get(
        f"/campaigns/{campaign.id}/posts/create",
        cookies={"access_token": auth_token},
    )
    assert response.status_code == 200
    html = response.text
    assert "New Post" in html
    assert 'name="title"' in html
    assert 'name="content"' in html
    assert 'name="channel_ids"' in html
    assert 'name="status"' in html
    assert "Add asset" in html


def test_create_post_submit_redirects(
    client, db_session, auth_token, campaign, channel, person
):
    token = _csrf_token(client)
    response = client.post(
        f"/campaigns/{campaign.id}/posts/create",
        data={
            "title": "My First Post",
            "content": "Hello world!",
            "channel_id": str(channel.id),
            "status": "draft",
            "scheduled_at": "",
            "csrf_token": token,
        },
        cookies={"access_token": auth_token, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert f"/campaigns/{campaign.id}" in response.headers["location"]

    from sqlalchemy import select

    post = db_session.scalar(select(Post).where(Post.title == "My First Post"))
    assert post is not None
    assert post.content == "Hello world!"
    assert post.channel_id == channel.id
    assert post.status == PostStatus.draft


def test_create_post_submit_links_selected_assets(
    client, db_session, auth_token, campaign, channel, person, asset
):
    campaign.assets.append(asset)
    db_session.commit()

    token = _csrf_token(client)
    response = client.post(
        f"/campaigns/{campaign.id}/posts/create",
        data={
            "title": "Instagram Asset Post",
            "content": "Hello world!",
            "channel_ids": [str(channel.id)],
            "asset_ids": [str(asset.id)],
            "status": "draft",
            "scheduled_at": "",
            "csrf_token": token,
        },
        cookies={"access_token": auth_token, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 302

    from sqlalchemy import select

    post = db_session.scalar(select(Post).where(Post.title == "Instagram Asset Post"))
    assert post is not None
    db_session.refresh(post)
    assert [linked_asset.id for linked_asset in post.assets] == [asset.id]


def test_create_post_validation_error_preserves_selected_assets(
    client, db_session, auth_token, campaign, channel, asset
):
    campaign.assets.append(asset)
    db_session.commit()

    token = _csrf_token(client)
    response = client.post(
        f"/campaigns/{campaign.id}/posts/create",
        data={
            "title": "",
            "content": "Needs a title",
            "channel_ids": [str(channel.id)],
            "asset_ids": [str(asset.id)],
            "status": "draft",
            "scheduled_at": "",
            "csrf_token": token,
        },
        cookies={"access_token": auth_token, "csrf_token": token},
    )

    assert response.status_code == 200
    html = response.text
    assert 'name="asset_ids"' in html
    assert f'value="{asset.id}"' in html
    assert "checked" in html


def test_edit_post_form_renders(
    client, db_session, auth_token, campaign, channel, person
):
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Editable Post",
        content="Original content",
        status=PostStatus.draft,
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()

    response = client.get(
        f"/campaigns/{campaign.id}/posts/{post.id}/edit",
        cookies={"access_token": auth_token},
    )
    assert response.status_code == 200
    html = response.text
    assert "Edit Post" in html
    assert "Editable Post" in html
    assert "Original content" in html


def test_edit_post_submit_updates(
    client, db_session, auth_token, campaign, channel, person
):
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Before Edit",
        content="Old content",
        status=PostStatus.draft,
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()

    token = _csrf_token(client)
    response = client.post(
        f"/campaigns/{campaign.id}/posts/{post.id}/edit",
        data={
            "title": "After Edit",
            "content": "New content",
            "channel_id": str(channel.id),
            "status": "planned",
            "scheduled_at": "2026-04-01T10:00",
            "csrf_token": token,
        },
        cookies={"access_token": auth_token, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 302

    db_session.refresh(post)
    assert post.title == "After Edit"
    assert post.content == "New content"
    assert post.status == PostStatus.planned


def test_edit_post_submit_updates_asset_links(
    client, db_session, auth_token, campaign, channel, person, asset
):
    campaign.assets.append(asset)
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Asset Edit",
        content="Old content",
        status=PostStatus.draft,
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()

    token = _csrf_token(client)
    response = client.post(
        f"/campaigns/{campaign.id}/posts/{post.id}/edit",
        data={
            "title": "Asset Edit",
            "content": "Old content",
            "channel_ids": [str(channel.id)],
            "asset_ids": [str(asset.id)],
            "status": "draft",
            "scheduled_at": "",
            "csrf_token": token,
        },
        cookies={"access_token": auth_token, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 302

    db_session.refresh(post)
    assert [linked_asset.id for linked_asset in post.assets] == [asset.id]


def test_delete_post_removes_record(
    client, db_session, auth_token, campaign, channel, person
):
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Doomed Post",
        status=PostStatus.draft,
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()
    post_id = post.id

    token = _csrf_token(client)
    response = client.post(
        f"/campaigns/{campaign.id}/posts/{post_id}/delete",
        data={"csrf_token": token},
        cookies={"access_token": auth_token, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert db_session.get(Post, post_id) is None


def test_create_post_missing_campaign_redirects(client, auth_token):
    fake_id = uuid4()
    response = client.get(
        f"/campaigns/{fake_id}/posts/create",
        cookies={"access_token": auth_token},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "error" in response.headers["location"]
