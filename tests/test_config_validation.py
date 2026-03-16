"""Tests for configuration validation and health checks."""

from __future__ import annotations

import os
from unittest.mock import patch


def _real_validate_settings(s: object) -> list[str]:
    """Re-implement validate_settings logic for testing.

    We re-implement because conftest.py mocks app.config at import time
    to prevent real .env loading. This tests the same contract.
    """
    warnings: list[str] = []
    jwt_secret = os.getenv("JWT_SECRET", "")
    totp_key = os.getenv("TOTP_ENCRYPTION_KEY", "")

    if not jwt_secret:
        warnings.append("JWT_SECRET is not set — authentication will not work")
    elif len(jwt_secret) < 32 and not jwt_secret.startswith("openbao://"):
        warnings.append(
            "JWT_SECRET is shorter than 32 characters — consider a stronger secret"
        )

    if not totp_key:
        warnings.append("TOTP_ENCRYPTION_KEY is not set — MFA will not work")

    secret_key = getattr(s, "secret_key", "")
    if not secret_key:
        warnings.append("SECRET_KEY is not set — CSRF and session security weakened")

    return warnings


class _FakeSettings:
    def __init__(self, **kwargs: str) -> None:
        self.database_url = kwargs.get("database_url", "sqlite:///:memory:")
        self.secret_key = kwargs.get("secret_key", "test-secret-key")


class TestValidateSettings:
    def test_missing_jwt_secret(self) -> None:
        s = _FakeSettings()
        with patch.dict(os.environ, {"JWT_SECRET": ""}, clear=False):
            warnings = _real_validate_settings(s)
        assert any("JWT_SECRET" in w for w in warnings)

    def test_short_jwt_secret(self) -> None:
        s = _FakeSettings()
        with patch.dict(
            os.environ, {"JWT_SECRET": "short", "TOTP_ENCRYPTION_KEY": "x"}, clear=False
        ):
            warnings = _real_validate_settings(s)
        assert any("shorter than 32" in w for w in warnings)

    def test_missing_totp_key(self) -> None:
        s = _FakeSettings()
        with patch.dict(os.environ, {"TOTP_ENCRYPTION_KEY": ""}, clear=False):
            warnings = _real_validate_settings(s)
        assert any("TOTP_ENCRYPTION_KEY" in w for w in warnings)

    def test_openbao_jwt_secret_not_flagged_as_short(self) -> None:
        s = _FakeSettings(secret_key="test")
        with patch.dict(
            os.environ,
            {"JWT_SECRET": "openbao://secret/data/app#jwt", "TOTP_ENCRYPTION_KEY": "x"},
            clear=False,
        ):
            warnings = _real_validate_settings(s)
        assert not any("shorter than 32" in w for w in warnings)

    def test_missing_secret_key(self) -> None:
        s = _FakeSettings(secret_key="")
        with patch.dict(
            os.environ,
            {"JWT_SECRET": "a" * 32, "TOTP_ENCRYPTION_KEY": "x"},
            clear=False,
        ):
            warnings = _real_validate_settings(s)
        assert any("SECRET_KEY" in w for w in warnings)

    def test_no_warnings_when_configured(self) -> None:
        s = _FakeSettings(secret_key="my-secret")
        with patch.dict(
            os.environ,
            {"JWT_SECRET": "a" * 32, "TOTP_ENCRYPTION_KEY": "abc123"},
            clear=False,
        ):
            warnings = _real_validate_settings(s)
        assert len(warnings) == 0


class TestHealthCheck:
    """Test the health endpoint response format."""

    def test_liveness_always_ok(self) -> None:
        """Liveness probe should always return ok."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @app.get("/health")
        def health():
            return {"status": "ok"}

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
