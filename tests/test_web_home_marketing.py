from app.config import settings


class TestMarketingPages:
    def test_public_routes_render(self, client):
        for path in ["/", "/services", "/plans", "/contact"]:
            response = client.get(path)
            assert response.status_code == 200

        body = response.text
        assert "Skip to content" in body
        assert 'id="main-content"' in body
        assert 'action="/contact/newsletter"' in body
        assert 'for="newsletter-email"' in body

    def test_www_redirects_to_canonical_host(self, client):
        original_host = settings.canonical_host
        original_scheme = settings.canonical_scheme
        settings.canonical_host = "dotmac.ng"
        settings.canonical_scheme = "https"

        try:
            response = client.get(
                "/services",
                headers={
                    "host": "www.dotmac.ng",
                    "x-forwarded-host": "www.dotmac.ng",
                    "x-forwarded-proto": "https",
                },
                follow_redirects=False,
            )
        finally:
            settings.canonical_host = original_host
            settings.canonical_scheme = original_scheme

        assert response.status_code == 308
        assert response.headers["location"] == "https://dotmac.ng/services"

    def test_invalid_newsletter_submission_returns_accessible_error(self, client):
        resp = client.get("/contact")
        csrf_token = resp.cookies.get("csrf_token", "")
        response = client.post(
            "/contact/newsletter",
            data={"newsletter_email": "not-an-email", "csrf_token": csrf_token},
            cookies={"csrf_token": csrf_token},
        )

        assert response.status_code == 400
        assert 'id="newsletter-error"' in response.text
        assert 'role="alert"' in response.text
        assert 'aria-invalid="true"' in response.text

    def test_valid_newsletter_submission_returns_status_message(self, client):
        resp = client.get("/contact")
        csrf_token = resp.cookies.get("csrf_token", "")
        response = client.post(
            "/contact/newsletter",
            data={"newsletter_email": "team@example.com", "csrf_token": csrf_token},
            cookies={"csrf_token": csrf_token},
        )

        assert response.status_code == 200
        assert "team@example.com" in response.text
        assert 'role="status"' in response.text
