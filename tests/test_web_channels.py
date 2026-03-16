from app.models.channel import ChannelProvider, ChannelStatus


class _FakeAdapter:
    async def connect(
        self, auth_code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict:
        return {
            "access_token": "access-123",
            "refresh_token": "refresh-123",
            "expires_in": 3600,
        }


class TestWebChannels:
    def test_channels_page_seeds_supported_providers(
        self, client, db_session, person, auth_session, auth_token
    ):
        from sqlalchemy import select

        from app.models.channel import Channel

        response = client.get(
            "/channels",
            cookies={"access_token": auth_token},
        )

        assert response.status_code == 200
        assert b"Add Channel" in response.content
        channels = list(db_session.scalars(select(Channel)).all())
        assert len(channels) == len(ChannelProvider)

    def test_connect_channel_form_renders(
        self, client, person, auth_session, auth_token
    ):
        response = client.get(
            "/channels/create",
            cookies={"access_token": auth_token},
        )

        assert response.status_code == 200
        assert b"Connect Channel" in response.content

    def test_connect_channel_submit_redirects_to_provider_oauth(
        self, client, person, auth_session, auth_token
    ):
        response = client.post(
            "/channels/create",
            data={
                "provider": "google_ads",
                "external_account_id": "1234567890",
            },
            cookies={"access_token": auth_token},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert (
            response.headers["location"]
            == "http://testserver/channels/google_ads/connect?external_account_id=1234567890"
        )

    def test_connect_channel_submit_redirects_to_meta_oauth(
        self, client, person, auth_session, auth_token
    ):
        response = client.post(
            "/channels/create",
            data={"provider": "meta"},
            cookies={"access_token": auth_token},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "http://testserver/channels/meta/connect"

    def test_manual_connect_stores_token(
        self, client, db_session, person, auth_session, auth_token, monkeypatch
    ):
        import sys

        from cryptography.fernet import Fernet
        from sqlalchemy import select

        from app.models.channel import Channel
        from app.services.credential_service import CredentialService

        mock_cfg = sys.modules["app.config"]
        monkeypatch.setattr(
            mock_cfg.settings, "encryption_key", Fernet.generate_key().decode()
        )

        response = client.post(
            "/channels/google_analytics/manual-connect",
            data={
                "external_account_id": "123456789",
                "access_token": "manual-access-token",
                "refresh_token": "manual-refresh-token",
            },
            cookies={"access_token": auth_token},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert (
            response.headers["location"]
            == "/channels?success=Channel+connected+with+manual+token"
        )

        channel = db_session.scalar(
            select(Channel).where(
                Channel.provider == ChannelProvider.google_analytics
            )
        )
        assert channel is not None
        assert channel.external_account_id == "123456789"
        assert channel.status == ChannelStatus.connected

        creds = CredentialService().decrypt(channel.credentials_encrypted)
        assert creds is not None
        assert creds["access_token"] == "manual-access-token"
        assert creds["refresh_token"] == "manual-refresh-token"
        assert creds["property_id"] == "123456789"

    def test_oauth_callback_stores_external_account_id_and_credentials(
        self, client, db_session, person, auth_session, auth_token, monkeypatch
    ):
        import sys

        from cryptography.fernet import Fernet
        from sqlalchemy import select

        from app.models.channel import Channel
        from app.services.credential_service import CredentialService
        from app.web.channels import _get_serializer

        mock_cfg = sys.modules["app.config"]
        monkeypatch.setattr(
            mock_cfg.settings, "encryption_key", Fernet.generate_key().decode()
        )
        monkeypatch.setattr(mock_cfg.settings, "twitter_client_id", "client-id")
        monkeypatch.setattr(
            "app.adapters.registry.get_adapter",
            lambda provider, **kwargs: _FakeAdapter(),
        )

        state = _get_serializer().dumps(
            {"provider": "twitter", "external_account_id": "2244994945"}
        )
        response = client.get(
            f"/channels/twitter/callback?code=test-code&state={state}",
            cookies={"access_token": auth_token, "oauth_state": state},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == (
            "/channels?success=Channel+connected+successfully"
        )

        channel = db_session.scalar(
            select(Channel).where(Channel.provider == ChannelProvider.twitter)
        )
        assert channel is not None
        assert channel.status == ChannelStatus.connected
        assert channel.external_account_id == "2244994945"
        assert channel.credentials_encrypted is not None

        creds = CredentialService().decrypt(channel.credentials_encrypted)
        assert creds is not None
        assert creds["access_token"] == "access-123"
        assert creds["refresh_token"] == "refresh-123"
        assert creds["account_id"] == "2244994945"
        assert creds["external_account_id"] == "2244994945"

    def test_oauth_callback_rejects_missing_external_account_id(
        self, client, db_session, person, auth_session, auth_token, monkeypatch
    ):
        import sys

        from cryptography.fernet import Fernet
        from sqlalchemy import select

        from app.models.channel import Channel
        from app.web.channels import _get_serializer

        mock_cfg = sys.modules["app.config"]
        monkeypatch.setattr(
            mock_cfg.settings, "encryption_key", Fernet.generate_key().decode()
        )
        monkeypatch.setattr(mock_cfg.settings, "linkedin_client_id", "client-id")
        monkeypatch.setattr(
            "app.adapters.registry.get_adapter",
            lambda provider, **kwargs: _FakeAdapter(),
        )

        state = _get_serializer().dumps({"provider": "linkedin"})
        response = client.get(
            f"/channels/linkedin/callback?code=test-code&state={state}",
            cookies={"access_token": auth_token, "oauth_state": state},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == (
            "/channels?error=Missing+LinkedIn+organization+ID"
        )

        channel = db_session.scalar(
            select(Channel).where(Channel.provider == ChannelProvider.linkedin)
        )
        assert channel is None

    def test_meta_oauth_callback_discovers_and_stores_assets(
        self, client, db_session, person, auth_session, auth_token, monkeypatch
    ):
        import sys

        from cryptography.fernet import Fernet
        from sqlalchemy import select

        from app.models.channel import Channel
        from app.services.credential_service import CredentialService
        from app.web.channels import _get_serializer

        mock_cfg = sys.modules["app.config"]
        monkeypatch.setattr(
            mock_cfg.settings, "encryption_key", Fernet.generate_key().decode()
        )
        monkeypatch.setattr(
            "app.web.channels.get_meta_oauth_config",
            lambda db: ("meta-app-id", "meta-app-secret"),
        )
        monkeypatch.setattr(
            "app.web.channels.get_adapter",
            lambda provider, **kwargs: _FakeAdapter(),
        )
        monkeypatch.setattr(
            "app.web.channels._discover_meta_assets",
            _fake_discover_meta_assets,
        )

        state = _get_serializer().dumps({"provider": "meta"})
        response = client.get(
            f"/channels/meta/callback?code=test-code&state={state}",
            cookies={"access_token": auth_token, "oauth_state": state},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/channels?success=Meta+connected+successfully"

        facebook_channel = db_session.scalar(
            select(Channel).where(
                Channel.provider == ChannelProvider.meta_facebook,
                Channel.external_account_id == "123456789012345",
            )
        )
        instagram_channel = db_session.scalar(
            select(Channel).where(
                Channel.provider == ChannelProvider.meta_instagram,
                Channel.external_account_id == "17841400000000000",
            )
        )
        assert facebook_channel is not None
        assert instagram_channel is not None
        assert facebook_channel.status == ChannelStatus.connected
        assert instagram_channel.status == ChannelStatus.connected

        creds = CredentialService().decrypt(instagram_channel.credentials_encrypted)
        assert creds is not None
        assert creds["access_token"] == "page-access-token"
        assert creds["account_id"] == "17841400000000000"


async def _fake_discover_meta_assets(access_token: str) -> list[dict[str, str]]:
    return [
        {
            "provider": "meta_facebook",
            "external_account_id": "123456789012345",
            "name": "DotMac Page",
            "access_token": "page-access-token",
        },
        {
            "provider": "meta_instagram",
            "external_account_id": "17841400000000000",
            "name": "dotmac_ig",
            "access_token": "page-access-token",
        },
    ]
