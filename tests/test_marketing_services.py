"""Tests for marketing domain services (Campaign, Channel, Post, Task, Credential)."""

import uuid

from app.models.campaign import CampaignStatus
from app.models.channel import ChannelProvider

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
