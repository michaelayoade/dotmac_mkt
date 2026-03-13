# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- Bump Jinja2 from 3.1.4 to >=3.1.6 to address CVE-2024-56201 and CVE-2024-56326 (sandbox bypass and code execution vulnerabilities) (PR #21)
- Bump cryptography from 42.0.8 to >=43.0.0 to incorporate security patches for RSA/EC operations and memory safety fixes in OpenSSL bindings (PR #20)
- Remove redundant `| safe` filter from `tojson` expressions in audit and billing admin templates — `tojson` is already HTML-safe and `| safe` suppressed Jinja2 auto-escaping (PR #2)
- Validate login `next` redirect parameter against a safe-URL allowlist to prevent open redirect attacks (PR #3)
- Sanitize user-controlled branding CSS before persistence, stripping `javascript:`, `expression()`, `@import`, and non-http `url()` schemes to prevent stored XSS (PR #4)
- Replace `{{ btn.icon | safe }}` with a CSS class-based icon lookup in table macros, eliminating a stored XSS vector in admin table action buttons (PR #5)
- Replace string-prefix path traversal guard with `Path.is_relative_to()` in storage service for more robust protection against symlink and relative-path bypasses (PR #6)
- Add regex format validation to CSRF token check — tokens must now match `[A-Za-z0-9_-]{32,}` instead of only requiring length ≥ 24, preventing crafted short-format tokens from passing validation (PR #7)
- Restrict `/metrics` Prometheus endpoint to loopback (`127.0.0.1`) by default, or require `Authorization: Bearer <METRICS_TOKEN>` when the env var is set, preventing unauthenticated access to operational data (PR #8)
- Move WebSocket JWT authentication from `?token=` URL query parameter to the `Sec-WebSocket-Protocol` subprotocol header, preventing tokens from appearing in server access logs and browser history (PR #9)
- Validate `logo_url` scheme in branding service, rejecting `javascript:`, `data:`, and non-HTTPS URIs to prevent URI injection attacks on the admin login page (PR #10)
- Fix `/health/ready` leaking raw exception strings (including connection strings and IP addresses) in the response body — internal errors are now logged at `exception` level and a generic `"unavailable"` is returned publicly (PR #11)
- Add magic-byte (file signature) verification to avatar upload service — client-supplied `Content-Type` headers are no longer trusted; JPEG/PNG/GIF/WebP signatures are verified against actual file contents (PR #12)
- Remove `unsafe-inline` and `unsafe-eval` from Content-Security-Policy `script-src` — inline scripts migrated to external files or per-request CSP nonces, substantially improving XSS protection (PR #13)
- Replace CORS wildcard `allow_methods=["*"]` and `allow_headers=["*"]` with explicit allowlists (`GET/POST/PUT/PATCH/DELETE/OPTIONS` and specific named headers), preventing TRACE method abuse and arbitrary header leakage (PR #14)
- Add `secure=True` to `access_token` and `refresh_token` cookies when HTTPS is detected via `x-forwarded-proto` or request scheme, preventing cookie transmission over plain HTTP in production deployments (PR #15)
- Fix X-Forwarded-For spoofing bypass in rate limiter — `X-Forwarded-For`/`X-Real-IP` headers are now only trusted when the direct client IP falls within a configured `TRUSTED_PROXY_CIDRS` range, preventing IP spoofing to bypass brute-force limits (PR #16)
- Fix rate limiting fail-open on Redis unavailability — auth endpoints (`/auth/login`, `/auth/mfa`, `/auth/register`) now return HTTP 503 instead of allowing all requests through when Redis is unreachable (PR #17)
- Add `.env.agent-swarm` to `.gitignore` to prevent accidental commit of live credentials (API keys, Telegram tokens) stored in that file (PR #18)
- Fix open redirect in login `next` parameter at the correct location (`app/web/auth.py:login_submit`) — `_safe_next_url()` helper validates the URL is a relative path without a scheme, replacing the earlier ineffective fix targeting the wrong file (PR #19)

### Added
- Security headers middleware (CSP, X-Frame-Options, HSTS, Referrer-Policy, Permissions-Policy)
- CORS middleware with configurable origins via `CORS_ORIGINS` env var
- Redis-backed sliding window rate limiting on auth endpoints (login, password-reset, MFA, register)
- Readiness health check at `/health/ready` (verifies DB + Redis connectivity)
- Gunicorn production config (`gunicorn.conf.py`) with worker tuning
- Centralized Jinja2 templates with custom filters (sanitize_html, nl2br, format_date, format_currency, timeago)
- Structured error responses with `request_id` correlation in every error payload
- Reusable `paginate()` helper for standardized paginated responses
- Startup configuration validation with warnings for missing secrets
- `TimestampMixin` for DRY `created_at`/`updated_at` columns
- CSRF auto-injection (meta tag + JS for forms, HTMX, and fetch)
- Token refresh manager (auto-refreshes JWT every 10 minutes)
- Form double-submit protection
- Query-parameter toast consumer (?success=, ?error=, etc.)
- `window.showToast()` global helper
- CLAUDE.md project reference with architecture and rules
- `.claude/rules/` with security, services, and templates patterns
- Makefile with 20 targets (lint, format, type-check, test, migrate, docker)
- Ruff, mypy, and coverage configuration in pyproject.toml
- Pre-commit hooks (ruff, detect-secrets, trailing whitespace)
- GitHub Actions CI pipeline (lint, type-check, test, security, pre-commit, docker build)
- `.dockerignore` for optimized Docker builds

### Changed
- Bump FastAPI from 0.111.0 to >=0.115.0 (validation bypass fixes, dependency injection improvements) (PR #22)
- Bump OpenTelemetry packages from 0.47b0/1.26.0 to >=0.50b0/>=1.29.0 stable beta with matching instrumentation packages (PR #24)
- Bump uvicorn (>=0.34.0), httpx (>=0.28.0), pydantic (>=2.11.0), python-dotenv (>=1.2.1), and celery (>=5.5.0) to latest patched versions (PR #23)
- Frontend accessibility improvements: responsive tables with horizontal scroll, mobile sidebar fixes, and ARIA enhancements across admin templates (PR #25)
- SQLAlchemy 2.0 pattern in `main.py`: `db.query()` → `select()` + `db.scalars()`
- Error responses now include `request_id` field for debugging

## [0.1.0] - 2026-02-12

### Added
- Initial starter template with authentication, RBAC, audit, and scheduler
- JWT-based auth with MFA (TOTP, SMS, Email)
- Celery workers with database-backed Beat scheduler
- Prometheus metrics and OpenTelemetry tracing
- JSON structured logging
