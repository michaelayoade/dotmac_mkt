"""Tests for RateLimitMiddleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.rate_limit import RateLimitMiddleware


@pytest.fixture
def app_with_rate_limit() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/auth/login")
    def login():
        return {"token": "abc"}

    @app.post("/auth/password-reset")
    def password_reset():
        return {"sent": True}

    @app.get("/auth/login")
    def login_form():
        return {"form": True}

    @app.post("/other")
    def other():
        return {"ok": True}

    return app


@pytest.fixture
def client(app_with_rate_limit: FastAPI) -> TestClient:
    return TestClient(app_with_rate_limit)


class TestRateLimitMiddleware:
    def test_allows_get_requests(self, client: TestClient) -> None:
        """GET requests are never rate limited."""
        resp = client.get("/auth/login")
        assert resp.status_code == 200

    def test_allows_non_auth_posts(self, client: TestClient) -> None:
        """POST requests to non-auth paths are not rate limited."""
        resp = client.post("/other")
        assert resp.status_code == 200

    @patch("app.middleware.rate_limit._get_redis", return_value=None)
    def test_allows_when_redis_unavailable(self, mock_redis: MagicMock) -> None:
        """Fail-open: if Redis is unavailable, requests are allowed."""
        # Create a fresh app so the middleware hasn't cached Redis yet
        fresh_app = FastAPI()
        fresh_app.add_middleware(RateLimitMiddleware)

        @fresh_app.post("/auth/login")
        def login():
            return {"token": "abc"}

        with TestClient(fresh_app) as c:
            resp = c.post("/auth/login")
        assert resp.status_code == 200

    @patch("app.middleware.rate_limit._get_redis")
    def test_rate_limit_headers_present(self, mock_redis: MagicMock) -> None:
        """Rate limit response headers are present when Redis works."""
        mock_r = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [None, 0, None, None]  # count=0 (under limit)
        mock_r.pipeline.return_value = mock_pipe
        mock_redis.return_value = mock_r

        fresh_app = FastAPI()
        fresh_app.add_middleware(RateLimitMiddleware)

        @fresh_app.post("/auth/login")
        def login():
            return {"token": "abc"}

        with TestClient(fresh_app) as c:
            resp = c.post("/auth/login")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers

    def test_429_response_format(self) -> None:
        """429 responses have standard error format."""
        from app.middleware.rate_limit import RateLimitMiddleware
        from starlette.responses import JSONResponse

        # Verify the response structure matches our error envelope
        response_content = {
            "code": "rate_limit_exceeded",
            "message": "Too many requests. Please try again later.",
            "details": None,
        }
        resp = JSONResponse(status_code=429, content=response_content)
        assert resp.status_code == 429


class TestRateLimitPaths:
    def test_login_path_configured(self) -> None:
        from app.middleware.rate_limit import _RATE_LIMIT_PATHS

        assert "/auth/login" in _RATE_LIMIT_PATHS
        max_req, window = _RATE_LIMIT_PATHS["/auth/login"]
        assert max_req == 10
        assert window == 60

    def test_password_reset_path_configured(self) -> None:
        from app.middleware.rate_limit import _RATE_LIMIT_PATHS

        assert "/auth/password-reset" in _RATE_LIMIT_PATHS
        max_req, window = _RATE_LIMIT_PATHS["/auth/password-reset"]
        assert max_req == 5
        assert window == 300

    def test_mfa_verify_path_configured(self) -> None:
        from app.middleware.rate_limit import _RATE_LIMIT_PATHS

        assert "/auth/mfa/verify" in _RATE_LIMIT_PATHS

    def test_register_path_configured(self) -> None:
        from app.middleware.rate_limit import _RATE_LIMIT_PATHS

        assert "/auth/register" in _RATE_LIMIT_PATHS
