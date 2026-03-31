"""Tests for marketing domain services (Campaign, Channel, Post, Task, Credential)."""

import uuid

import httpx

from app.adapters.base import PublishResult, UpdateResult
from app.models.asset import Asset, AssetType
from app.models.campaign import CampaignStatus
from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.models.post import Post, PostStatus
from app.models.post_delivery import PostDelivery, PostDeliveryStatus

# ────────────────────────── CampaignService ──────────────────────────


class TestCampaignService:
    def test_create_campaign(self, db_session, person):
        from app.schemas.campaign import CampaignCreate
        from app.services.campaign_service import CampaignService

        svc = CampaignService(db_session)
        data = CampaignCreate(
            name="Service Campaign", description="Created via service"
        )
        result = svc.create(data, created_by=person.id)
        db_session.commit()

        assert result.id is not None
        assert result.name == "Service Campaign"
        assert result.status == CampaignStatus.draft
        assert result.created_by == person.id

    def test_get_by_id(self, db_session, person):
        from app.schemas.campaign import CampaignCreate
        from app.services.campaign_service import CampaignService

        svc = CampaignService(db_session)
        created = svc.create(
            CampaignCreate(name="Lookup Campaign"), created_by=person.id
        )
        db_session.commit()

        fetched = svc.get_by_id(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "Lookup Campaign"

    def test_get_by_id_not_found(self, db_session):
        from app.services.campaign_service import CampaignService

        svc = CampaignService(db_session)
        assert svc.get_by_id(uuid.uuid4()) is None

    def test_list_all(self, db_session, person):
        from app.schemas.campaign import CampaignCreate
        from app.services.campaign_service import CampaignService

        svc = CampaignService(db_session)
        for i in range(3):
            svc.create(CampaignCreate(name=f"List Camp {i}"), created_by=person.id)
        db_session.commit()

        results = svc.list_all()
        assert len(results) >= 3

    def test_list_all_with_status_filter(self, db_session, person):
        from app.schemas.campaign import CampaignCreate
        from app.services.campaign_service import CampaignService

        svc = CampaignService(db_session)
        svc.create(
            CampaignCreate(name="Active One", status=CampaignStatus.active),
            created_by=person.id,
        )
        svc.create(
            CampaignCreate(name="Draft One", status=CampaignStatus.draft),
            created_by=person.id,
        )
        db_session.commit()

        active = svc.list_all(status=CampaignStatus.active)
        assert all(c.status == CampaignStatus.active for c in active)

    def test_update_campaign(self, db_session, person):
        from app.schemas.campaign import CampaignCreate, CampaignUpdate
        from app.services.campaign_service import CampaignService

        svc = CampaignService(db_session)
        created = svc.create(CampaignCreate(name="Original Name"), created_by=person.id)
        db_session.commit()

        updated = svc.update(
            created.id,
            CampaignUpdate(name="Updated Name", status=CampaignStatus.active),
        )
        db_session.commit()

        assert updated.name == "Updated Name"
        assert updated.status == CampaignStatus.active


# ────────────────────────── ChannelService ──────────────────────────


class TestChannelService:
    def test_create_channel(self, db_session):
        from app.schemas.channel import ChannelCreate
        from app.services.channel_service import ChannelService

        svc = ChannelService(db_session)
        data = ChannelCreate(name="Svc Twitter", provider=ChannelProvider.twitter)
        result = svc.create(data)
        db_session.commit()

        assert result.id is not None
        assert result.name == "Svc Twitter"
        assert result.provider == ChannelProvider.twitter

    def test_list_channels(self, db_session):
        from app.schemas.channel import ChannelCreate
        from app.services.channel_service import ChannelService

        svc = ChannelService(db_session)
        svc.create(ChannelCreate(name="Ch A", provider=ChannelProvider.linkedin))
        svc.create(ChannelCreate(name="Ch B", provider=ChannelProvider.google_ads))
        db_session.commit()

        results = svc.list_all()
        assert len(results) >= 2

    def test_update_external_account_id(self, db_session):
        from app.schemas.channel import ChannelCreate
        from app.services.channel_service import ChannelService

        svc = ChannelService(db_session)
        channel = svc.create(
            ChannelCreate(name="Ch A", provider=ChannelProvider.linkedin)
        )
        db_session.commit()

        updated = svc.update_external_account_id(channel.id, "org-123")
        db_session.commit()

        assert updated.external_account_id == "org-123"


# ────────────────────────── PostService ──────────────────────────


class TestPostService:
    def test_create_post(self, db_session, campaign, channel, person):
        from app.schemas.post import PostCreate
        from app.services.post_service import PostService

        svc = PostService(db_session)
        data = PostCreate(
            title="Svc Post",
            content="Hello from the service layer",
            campaign_id=campaign.id,
            channel_id=channel.id,
        )
        result = svc.create(data, created_by=person.id)
        db_session.commit()

        assert result.id is not None
        assert result.title == "Svc Post"
        assert result.campaign_id == campaign.id
        assert result.channel_id == channel.id
        assert result.created_by == person.id


class _SuccessfulPublishAdapter:
    async def publish_post(self, content, *, media_urls=None, title=None):
        return PublishResult(external_post_id=f"ok-{title or 'post'}")


class _FailingPublishAdapter:
    async def publish_post(self, content, *, media_urls=None, title=None):
        raise RuntimeError("remote publish failed")


class _RecordingPublishAdapter:
    def __init__(self) -> None:
        self.media_urls = None

    async def publish_post(self, content, *, media_urls=None, title=None):
        self.media_urls = media_urls
        return PublishResult(external_post_id=f"ok-{title or 'post'}")


class _RecordingMutableAdapter:
    def __init__(self) -> None:
        self.updated = []
        self.deleted = []
        self.supports_remote_update = True
        self.supports_remote_delete = True

    async def update_post(
        self, external_post_id, content, *, media_urls=None, title=None
    ):
        self.updated.append(
            {
                "external_post_id": external_post_id,
                "content": content,
                "media_urls": media_urls,
                "title": title,
            }
        )
        return UpdateResult(external_post_id=external_post_id)

    async def delete_post(self, external_post_id):
        self.deleted.append(external_post_id)


class TestPublishingService:
    def test_publish_marks_failed_delivery_but_keeps_successful_ones(
        self, db_session, campaign, person
    ):
        from app.services.publishing_service import PublishingService

        success_channel = Channel(
            name="X Channel",
            provider=ChannelProvider.twitter,
            status=ChannelStatus.connected,
            credentials_encrypted=b"creds",
        )
        failing_channel = Channel(
            name="LinkedIn Channel",
            provider=ChannelProvider.linkedin,
            status=ChannelStatus.connected,
            credentials_encrypted=b"creds",
        )
        db_session.add_all([success_channel, failing_channel])
        db_session.flush()

        post = Post(
            campaign_id=campaign.id,
            channel_id=success_channel.id,
            title="Cross Platform Post",
            content="Shared content",
            status=PostStatus.draft,
            created_by=person.id,
        )
        db_session.add(post)
        db_session.flush()
        db_session.add_all(
            [
                PostDelivery(
                    post_id=post.id,
                    channel_id=success_channel.id,
                    provider=success_channel.provider,
                    status=PostDeliveryStatus.draft,
                ),
                PostDelivery(
                    post_id=post.id,
                    channel_id=failing_channel.id,
                    provider=failing_channel.provider,
                    status=PostDeliveryStatus.draft,
                ),
            ]
        )
        db_session.commit()

        svc = PublishingService(db_session)

        def _fake_adapter(channel):
            if channel.id == success_channel.id:
                return _SuccessfulPublishAdapter()
            return _FailingPublishAdapter()

        svc._get_channel_adapter = _fake_adapter  # type: ignore[method-assign]

        result = svc.publish(post.id)
        db_session.commit()

        assert result.status == PostStatus.published
        deliveries = {
            delivery.channel_id: delivery
            for delivery in db_session.query(PostDelivery).filter_by(post_id=post.id).all()
        }
        assert deliveries[success_channel.id].status == PostDeliveryStatus.published
        assert deliveries[success_channel.id].external_post_id == "ok-Cross Platform Post"
        assert deliveries[success_channel.id].error_message is None
        assert deliveries[failing_channel.id].status == PostDeliveryStatus.failed
        assert deliveries[failing_channel.id].external_post_id is None
        assert deliveries[failing_channel.id].error_message == "remote publish failed"

    def test_publish_raises_when_all_deliveries_fail(self, db_session, campaign, person):
        from app.services.publishing_service import PublishingService

        failing_channel = Channel(
            name="LinkedIn Channel",
            provider=ChannelProvider.linkedin,
            status=ChannelStatus.connected,
            credentials_encrypted=b"creds",
        )
        db_session.add(failing_channel)
        db_session.flush()

        post = Post(
            campaign_id=campaign.id,
            channel_id=failing_channel.id,
            title="Broken Cross Platform Post",
            content="Shared content",
            status=PostStatus.draft,
            created_by=person.id,
        )
        db_session.add(post)
        db_session.flush()
        db_session.add(
            PostDelivery(
                post_id=post.id,
                channel_id=failing_channel.id,
                provider=failing_channel.provider,
                status=PostDeliveryStatus.draft,
            )
        )
        db_session.commit()

        svc = PublishingService(db_session)
        svc._get_channel_adapter = lambda channel: _FailingPublishAdapter()  # type: ignore[method-assign]

        import pytest

        with pytest.raises(RuntimeError, match="remote publish failed"):
            svc.publish(post.id)

        db_session.refresh(post)
        delivery = db_session.query(PostDelivery).filter_by(post_id=post.id).one()
        assert post.status == PostStatus.draft
        assert post.external_post_id is None
        assert delivery.status == PostDeliveryStatus.failed
        assert delivery.error_message == "remote publish failed"

    def test_publish_uses_preview_url_for_instagram_assets(
        self, db_session, campaign, person, channel, asset
    ):
        from app.services.publishing_service import PublishingService

        post = Post(
            campaign_id=campaign.id,
            channel_id=channel.id,
            title="Instagram Post",
            content="Caption",
            status=PostStatus.draft,
            created_by=person.id,
        )
        post.assets.append(asset)
        db_session.add(post)
        db_session.commit()

        adapter = _RecordingPublishAdapter()
        svc = PublishingService(db_session)
        svc._get_channel_adapter = lambda channel: adapter  # type: ignore[method-assign]

        svc.publish(post.id)

        assert adapter.media_urls == [asset.preview_url]

    def test_publishability_reports_unsupported_instagram_webp_assets(
        self, db_session, campaign, person, channel
    ):
        from app.services.publishing_service import PublishingService

        asset = Asset(
            name="webp-upload",
            asset_type=AssetType.image,
            drive_file_id="webp123",
            drive_url="https://drive.google.com/file/d/webp123/view",
            mime_type="image/webp",
        )
        post = Post(
            campaign_id=campaign.id,
            channel_id=channel.id,
            title="Instagram WEBP Post",
            content="Caption",
            status=PostStatus.draft,
            created_by=person.id,
        )
        post.assets.append(asset)
        db_session.add_all([asset, post])
        db_session.commit()

        issues = PublishingService(db_session).publishability_issues(post)

        assert issues
        assert next(iter(issues.values())) == (
            "Instagram does not support image/webp assets. "
            "Upload a JPG or PNG instead."
        )

    def test_update_published_post_uses_single_delivery_target(
        self, db_session, campaign, person
    ):
        from app.services.publishing_service import PublishingService

        channel = Channel(
            name="Facebook Channel",
            provider=ChannelProvider.meta_facebook,
            status=ChannelStatus.connected,
            credentials_encrypted=b"creds",
        )
        db_session.add(channel)
        db_session.flush()

        post = Post(
            campaign_id=campaign.id,
            channel_id=None,
            title="Delivery-backed Post",
            content="Before",
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
                external_post_id="fb-delivery-1",
            )
        )
        db_session.commit()

        adapter = _RecordingMutableAdapter()
        svc = PublishingService(db_session)
        svc._get_channel_adapter = lambda channel: adapter  # type: ignore[method-assign]

        svc.update_published_post(
            post.id,
            title="After",
            content="Updated content",
            channel_id=None,
            scheduled_at=None,
        )

        db_session.refresh(post)
        delivery = db_session.query(PostDelivery).filter_by(post_id=post.id).one()
        assert adapter.updated[0]["external_post_id"] == "fb-delivery-1"
        assert post.title == "After"
        assert post.content == "Updated content"
        assert delivery.content_override == "Updated content"

    def test_delete_published_post_uses_single_delivery_target(
        self, db_session, campaign, person
    ):
        from app.services.publishing_service import PublishingService

        channel = Channel(
            name="Facebook Channel",
            provider=ChannelProvider.meta_facebook,
            status=ChannelStatus.connected,
            credentials_encrypted=b"creds",
        )
        db_session.add(channel)
        db_session.flush()

        post = Post(
            campaign_id=campaign.id,
            channel_id=None,
            title="Delete Delivery-backed Post",
            content="To delete",
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
                external_post_id="fb-delivery-2",
            )
        )
        db_session.commit()

        adapter = _RecordingMutableAdapter()
        svc = PublishingService(db_session)
        svc._get_channel_adapter = lambda channel: adapter  # type: ignore[method-assign]

        svc.delete_published_post(post.id)

        assert adapter.deleted == ["fb-delivery-2"]
        assert db_session.get(Post, post.id) is None


class _FakeHTTPResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)
        self.request = httpx.Request("GET", "https://graph.facebook.com")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "request failed", request=self.request, response=self
            )


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return self._responses.pop(0)

    async def get(self, *args, **kwargs):
        return self._responses.pop(0)


class TestMetaAdapter:
    def test_instagram_publish_resolves_final_media_id(self, monkeypatch):
        from app.adapters.meta import MetaAdapter
        from app.models.channel import ChannelProvider

        responses = [
            _FakeHTTPResponse(200, {"id": "container-1"}),
            _FakeHTTPResponse(200, {"id": "publish-1"}),
            _FakeHTTPResponse(400, {"error": {"message": "not found"}}),
            _FakeHTTPResponse(
                200,
                {
                    "data": [
                        {
                            "id": "final-media-1",
                            "caption": "Caption",
                            "permalink": "https://instagram.com/p/final-media-1",
                        }
                    ]
                },
            ),
        ]
        monkeypatch.setattr(
            "app.adapters.meta.httpx.AsyncClient",
            lambda *args, **kwargs: _FakeAsyncClient(responses),
        )

        adapter = MetaAdapter(
            access_token="token",
            account_id="acct-1",
            provider=ChannelProvider.meta_instagram,
        )
        result = __import__("asyncio").run(
            adapter.publish_post("Caption", media_urls=["https://example.com/test.jpg"])
        )

        assert result.external_post_id == "final-media-1"
        assert result.url == "https://instagram.com/p/final-media-1"

    def test_instagram_publish_raises_when_media_cannot_be_resolved(
        self, monkeypatch
    ):
        from app.adapters.meta import MetaAdapter
        from app.models.channel import ChannelProvider

        responses = [
            _FakeHTTPResponse(200, {"id": "container-1"}),
            _FakeHTTPResponse(200, {"id": "publish-1"}),
            _FakeHTTPResponse(400, {"error": {"message": "not found"}}),
            _FakeHTTPResponse(200, {"data": []}),
            _FakeHTTPResponse(400, {"error": {"message": "not found"}}),
            _FakeHTTPResponse(200, {"data": []}),
            _FakeHTTPResponse(400, {"error": {"message": "not found"}}),
            _FakeHTTPResponse(200, {"data": []}),
        ]
        monkeypatch.setattr(
            "app.adapters.meta.httpx.AsyncClient",
            lambda *args, **kwargs: _FakeAsyncClient(responses),
        )

        async def _noop_sleep(*args, **kwargs):
            return None

        monkeypatch.setattr("app.adapters.meta.asyncio.sleep", _noop_sleep)

        adapter = MetaAdapter(
            access_token="token",
            account_id="acct-1",
            provider=ChannelProvider.meta_instagram,
        )

        import pytest

        with pytest.raises(
            ValueError, match="Instagram publish failed to resolve a live media object"
        ):
            __import__("asyncio").run(
                adapter.publish_post(
                    "Caption", media_urls=["https://example.com/test.jpg"]
                )
            )


# ────────────────────────── MktTaskService ──────────────────────────


class TestMktTaskService:
    def test_create_task(self, db_session, campaign, person):
        from app.schemas.task import TaskCreate
        from app.services.task_service import MktTaskService

        svc = MktTaskService(db_session)
        data = TaskCreate(
            title="Svc Task",
            description="Task created via service",
            campaign_id=campaign.id,
            assignee_id=person.id,
        )
        result = svc.create(data, created_by=person.id)
        db_session.commit()

        assert result.id is not None
        assert result.title == "Svc Task"
        assert result.campaign_id == campaign.id
        assert result.created_by == person.id


# ────────────────────────── CredentialService ──────────────────────────


class TestCredentialService:
    def test_encrypt_decrypt_roundtrip(self, monkeypatch):
        import sys

        from cryptography.fernet import Fernet

        # Generate a real Fernet key for this test
        real_key = Fernet.generate_key().decode()

        # Patch settings on the mocked app.config module
        mock_cfg = sys.modules["app.config"]
        monkeypatch.setattr(mock_cfg.settings, "encryption_key", real_key)

        from app.services.credential_service import CredentialService

        svc = CredentialService()

        original = {
            "access_token": "EAAGtest123",
            "refresh_token": "refresh-xyz",
            "expires_in": 3600,
        }

        encrypted = svc.encrypt(original)
        assert isinstance(encrypted, bytes)
        assert encrypted != original

        decrypted = svc.decrypt(encrypted)
        assert decrypted == original

    def test_decrypt_invalid_returns_none(self, monkeypatch):
        import sys

        from cryptography.fernet import Fernet

        real_key = Fernet.generate_key().decode()

        mock_cfg = sys.modules["app.config"]
        monkeypatch.setattr(mock_cfg.settings, "encryption_key", real_key)

        from app.services.credential_service import CredentialService

        svc = CredentialService()
        result = svc.decrypt(b"not-a-valid-fernet-token")
        assert result is None
