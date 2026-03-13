"""Security headers middleware.

Adds OWASP-recommended HTTP security headers to every response.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects security headers into every HTTP response."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        response: Response = await call_next(request)  # type: ignore[call-arg]

        # Prevent MIME-sniffing
        response.headers.setdefault("X-Content-Type-Options", "nosniff")

        # Clickjacking protection
        response.headers.setdefault("X-Frame-Options", "DENY")

        # XSS filter (legacy browsers)
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")

        # Control referrer leakage
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )

        # Restrict browser features
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )

        # Content Security Policy — restrictive but practical
        response.headers.setdefault(
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data: https:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            ),
        )

        # HSTS — only set when behind TLS (proxy sets X-Forwarded-Proto)
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        return response
