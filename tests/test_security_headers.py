"""Tests for SecurityHeadersMiddleware."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.security_headers import SecurityHeadersMiddleware


@pytest.fixture
def app_with_headers() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"ok": True}

    return app


@pytest.fixture
def client(app_with_headers: FastAPI) -> TestClient:
    return TestClient(app_with_headers)


class TestSecurityHeaders:
    def test_x_content_type_options(self, client: TestClient) -> None:
        resp = client.get("/test")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_x_frame_options(self, client: TestClient) -> None:
        resp = client.get("/test")
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_x_xss_protection(self, client: TestClient) -> None:
        resp = client.get("/test")
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"

    def test_referrer_policy(self, client: TestClient) -> None:
        resp = client.get("/test")
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client: TestClient) -> None:
        resp = client.get("/test")
        assert "camera=()" in resp.headers["Permissions-Policy"]
        assert "microphone=()" in resp.headers["Permissions-Policy"]

    def test_content_security_policy(self, client: TestClient) -> None:
        resp = client.get("/test")
        csp = resp.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "form-action 'self'" in csp

    def test_no_unsafe_eval_in_csp(self, client: TestClient) -> None:
        resp = client.get("/test")
        csp = resp.headers["Content-Security-Policy"]
        assert "'unsafe-eval'" not in csp

    def test_no_cdn_allowlist_in_csp(self, client: TestClient) -> None:
        resp = client.get("/test")
        csp = resp.headers["Content-Security-Policy"]
        assert "cdn.tailwindcss.com" not in csp
        assert "unpkg.com" not in csp
        assert "cdn.jsdelivr.net" not in csp

    def test_no_hsts_without_https(self, client: TestClient) -> None:
        resp = client.get("/test")
        assert "Strict-Transport-Security" not in resp.headers

    def test_hsts_with_https_proxy(self, client: TestClient) -> None:
        resp = client.get("/test", headers={"X-Forwarded-Proto": "https"})
        assert "Strict-Transport-Security" in resp.headers
        assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]

    def test_does_not_overwrite_existing_headers(self) -> None:
        """If a route sets a custom CSP, the middleware should not overwrite it."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/custom-csp")
        def custom_csp():
            from starlette.responses import JSONResponse

            resp = JSONResponse({"ok": True})
            resp.headers["Content-Security-Policy"] = "default-src 'none'"
            return resp

        client = TestClient(app)
        resp = client.get("/custom-csp")
        assert resp.headers["Content-Security-Policy"] == "default-src 'none'"
