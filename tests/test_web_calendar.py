from datetime import UTC, datetime

from app.models.post import Post, PostStatus


def _csrf_token(client) -> str:
    response = client.get("/health")
    return response.cookies.get("csrf_token", "")


def test_calendar_example_csv_downloads_expected_columns(
    client, auth_token, campaign, channel
):
    response = client.get(
        "/calendar/import/example.csv",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "content-calendar-example.csv" in response.headers["content-disposition"]
    body = response.text
    assert "post_id,campaign_name,campaign_id,title,content,status,scheduled_at,channels,channel_ids,channel_overrides_json" in body
    assert campaign.name in body
    assert channel.name in body


def test_calendar_import_creates_post_and_delivery(
    client, db_session, auth_token, campaign, channel, person
):
    csrf_token = _csrf_token(client)
    csv_body = "\n".join(
        [
            "post_id,campaign_name,campaign_id,title,content,status,scheduled_at,channels,channel_ids,channel_overrides_json",
            (
                f',"{campaign.name}",{campaign.id},"April teaser","Launch copy",planned,2026-04-10T09:00:00Z,'
                f'"{channel.name}",{channel.id},"{{""{channel.name}"": ""Platform-specific copy""}}"'
            ),
        ]
    )

    response = client.post(
        "/calendar/import",
        cookies={"access_token": auth_token, "csrf_token": csrf_token},
        data={"csrf_token": csrf_token},
        files={"file": ("calendar.csv", csv_body, "text/csv")},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "Imported+1+new+posts+and+updated+0+existing+posts" in response.headers["location"]

    post = db_session.query(Post).filter(Post.title == "April teaser").one()
    assert post.campaign_id == campaign.id
    assert post.created_by == person.id
    assert post.status == PostStatus.planned
    assert post.scheduled_at is not None
    assert len(post.deliveries) == 1
    assert post.deliveries[0].channel_id == channel.id
    assert post.deliveries[0].content_override == "Platform-specific copy"


def test_calendar_import_updates_existing_post_by_post_id(
    client, db_session, auth_token, campaign, channel, person
):
    post = Post(
        campaign_id=campaign.id,
        channel_id=channel.id,
        title="Old title",
        content="Old content",
        status=PostStatus.draft,
        scheduled_at=datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
        created_by=person.id,
    )
    db_session.add(post)
    db_session.commit()

    csrf_token = _csrf_token(client)
    csv_body = "\n".join(
        [
            "post_id,campaign_name,campaign_id,title,content,status,scheduled_at,channels,channel_ids,channel_overrides_json",
            (
                f'{post.id},"{campaign.name}",{campaign.id},"Updated title","Updated content",planned,2026-04-12T14:30:00Z,'
                f'"{channel.name}",{channel.id},"{{}}"'
            ),
        ]
    )

    response = client.post(
        "/calendar/import",
        cookies={"access_token": auth_token, "csrf_token": csrf_token},
        data={"csrf_token": csrf_token},
        files={"file": ("calendar.csv", csv_body, "text/csv")},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "Imported+0+new+posts+and+updated+1+existing+posts" in response.headers["location"]

    db_session.refresh(post)
    assert post.title == "Updated title"
    assert post.content == "Updated content"
    assert post.status == PostStatus.planned
    assert post.scheduled_at is not None
