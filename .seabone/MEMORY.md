# Seabone Memory — dotmac_starter

## Project Facts

### From CLAUDE.md
> # Starter Template
> 
> Multi-tenant FastAPI starter with auth, RBAC, audit, and scheduler. FastAPI + SQLAlchemy 2.0 + Celery + Jinja2/Alpine.js.
> 
> ## Quick Commands
> 
> ```bash
> # Quality (or use: make check)
> make lint                        # ruff check app/
> make format                      # ruff format + fix
> make type-check                  # mypy app/
> 
> # Testing (or use: make test)
> pytest tests/path/test_file.py -v  # Specific test
> pytest -x --tb=short               # Stop on first failure
> make test-cov                      # With coverage
> 
> # Database
> make migrate                     # alembic upgrade head
> make migrate-new msg="desc"      # New migration

### From README
> # Starter Template
> 
> A production-ready FastAPI starter template with enterprise-grade features including authentication, RBAC, audit logging, background jobs, and full observability.
> 
> ## Features
> 
> - **Authentication & Security**
>   - JWT-based authentication with refresh token rotation
>   - Multi-factor authentication (TOTP, SMS, Email)
>   - API key management with rate limiting

### Stack Detection
- Build: pyproject.toml detected
- App dir: app/ present
- Tests: tests/ present

## Known Patterns

### CONFIRMED FIXED (source-verified pass 3 2026-02-27)
- c1-1: `.env.agent-swarm` in `.gitignore:40` ✓
- c1-2: `_org_branding_head.html:8` — no `| safe`; `sanitize_branding_css()` sanitises at save ✓
- c1-3: `app/web/auth.py:59` — `_safe_next_url()` validates scheme/host ✓
- c1-8: `app/api/ws.py:32-41` — JWT via `Sec-WebSocket-Protocol` header, not query param ✓
- c1-9: `app/middleware/csrf.py:23,31` — regex `[A-Za-z0-9_-]{32,}` enforced ✓
- c1-10: `/health/ready` returns generic "unavailable" on error ✓
- c1-11: `/metrics` requires bearer token or loopback IP ✓
- c1-14: `avatar.py` magic-byte sniffing + declared/sniffed cross-check ✓
- c1-16: `app/web/auth.py:100,110` — `secure=is_secure` on both cookies ✓
- c1-17: `app/main.py:96-103` — explicit CORS method/header allowlists ✓
- c1-18: `rate_limit.py:67-93` — trusted proxy CIDR validation ✓
- c1-20: `rate_limit.py:141-148` — Redis unavailable on auth paths → HTTP 503 ✓
- `| safe` on `tojson` in audit/billing detail templates — FIXED PR #2 (c1-5, c1-6) ✓
- `branding_assets.py` — SVG safety validation + `_safe_asset_path()` path traversal guard ✓
- `storage.py` — `LocalStorage._resolve_path()` traversal guard ✓

### OPEN / UNRESOLVED
- c1-7: `app/middleware/security_headers.py:43` — CSP still has `'unsafe-inline'`/`'unsafe-eval'`. Agents ran PRs but code unchanged. (large effort)
- c1-19: `app/services/auth.py:42` — `hash_api_key()` still SHA-256. Fix PR did not land. (small effort)
- c2-1: `app/services/auth_flow.py:529,566` — TOTP no used-code cache; replay within 30s window (NEW)
- c2-2: `app/services/auth_flow.py:152` — API refresh cookie `Secure=False` by default (NEW)
- c2-3: `app/services/auth_flow.py:441` — login timing side-channel enables username enumeration (NEW)
- c2-4: `app/services/avatar.py:91-95` — `delete_avatar()` no path traversal guard (NEW); cf. `branding_assets._safe_asset_path()` pattern
- c2-5: `app/services/email.py:99` — `person_name` HTML-unescaped in password reset email (NEW)
- c5-1: `app/api/file_uploads.py:47` — list_file_uploads returns ALL users' files; no ownership filter (HIGH)
- c5-2: `app/api/file_uploads.py:74` — delete_file_upload no ownership check; any user can delete any file (HIGH)
- c5-3: `app/api/file_uploads.py:14` — uploaded_by never set; ownership tracking broken (MEDIUM, trivial)
- c5-4: `app/services/auth_flow.py:736` — password reset JWT not single-use; replayable within TTL (MEDIUM, small)
- c5-5: `app/services/auth_flow.py:554` — MFA token JWT not invalidated after mfa_verify(); reusable within 5 min (MEDIUM, small)
- c5-6: `app/services/file_upload.py:36` — file upload trusts client MIME type; no magic-byte check (MEDIUM, small)
- c9-1: `app/services/auth_dependencies.py:94-118` — require_audit_auth session-token and API-key paths skip scope/role check; any user can read all audit events (HIGH, small)
- c9-2: `app/web/auth.py:118-122` — GET /admin/logout clears cookies but never revokes session in DB; refresh token remains valid (MEDIUM, small)
- c9-3: `app/services/storage.py:50` — LocalStorage.save() doesn't apply _resolve_path() guard present in delete()/exists() (LOW, trivial)
- c9-4: `app/web/file_uploads.py:177,184` — exception strings URL-unencoded in redirect query param; leaks internal errors (LOW, trivial)
- c9-5: `app/api/file_uploads.py:22` — entire file read into memory before size check; memory DoS risk (LOW, small)

### OPEN QUALITY FINDINGS (quality-c2, first quality scan 2026-02-27)
- quality-c2-1: `app/services/auth.py:115` — `db.commit()` in services (87×/9 files); should be `db.flush()` — CRITICAL, large
- quality-c2-2: `app/services/auth_flow.py:80` — `db.query()` instead of `select()` (56×/11 files) — HIGH, large
- quality-c2-3: `app/services/auth.py:96` — `HTTPException` raised in service layer (16 files) — HIGH, large
- quality-c2-4: `app/services/email.py:68` — SMTP server not used as context manager, socket leak risk — MEDIUM, trivial
- quality-c2-5: `app/services/storage.py:143` — `except Exception:` in S3Storage.exists() with no logging — MEDIUM, trivial
- quality-c2-6: `app/services/websocket_manager.py:52` — `except Exception:` on WS send with no logging — MEDIUM, trivial
- quality-c2-7: `app/services/email.py:12` — `_env_value`/`_env_int`/`_env_bool` duplicated in email.py, auth_flow.py, scheduler_config.py — MEDIUM, small
- quality-c2-8: `app/services/auth_flow.py:283` — `_load_rbac_claims` missing return type annotation — LOW, trivial
- quality-c2-9: `app/services/scheduler_config.py:8` — missing blank line before `logger=` (ruff formatting) — LOW, trivial

### OPEN QUALITY FINDINGS (quality-c6, 2026-02-27)
- quality-c6-1: `app/services/auth_flow.py:1` — no logger defined; login/MFA/password-reset/refresh events completely invisible — HIGH, trivial
- quality-c6-2: `app/services/auth.py:1` — no logger defined; credential/session/API-key ops silent — MEDIUM, trivial
- quality-c6-3: `app/services/common.py:24` — `apply_ordering`/`apply_pagination` are dead code (all 7 consumers import from query_utils.py) — LOW, trivial
- quality-c6-4: `app/api/ws.py:68` — `except Exception:` disconnects WebSocket silently; failure reason lost — LOW, trivial
- quality-c6-5: `app/services/auth_flow.py:228` — magic numbers for MFA TTL (5 min), lockout threshold (5), lockout duration (15 min) — LOW, trivial
- quality-c6-6: `app/services/response.py:14` — ListResponseMixin.list/list_response untyped db + *args/**kwargs — LOW, trivial
- quality-c6-7: `app/api/ws.py:56` — `from uuid import UUID` lazy-imported inside function body — LOW, trivial
- quality-c6-8: `app/services/scheduler_config.py` — no unit tests for get_celery_config() — LOW, small

### OPEN QUALITY FINDINGS (quality-c10, 2026-02-28)
- quality-c10-1: `app/services/auth_dependencies.py:1` — no logger; auth failures (invalid token, expired session, forbidden) invisible in logs — HIGH, trivial
- quality-c10-2: `app/services/branding.py:96,119` — branding settings stored under SettingDomain.scheduler (no branding domain exists); data namespace bug — HIGH, small
- quality-c10-3: `app/services/person.py:1` — no logger; person CRUD invisible in logs — MEDIUM, trivial
- quality-c10-4: `app/services/rbac.py:1` — no logger; role/permission CRUD invisible in logs — MEDIUM, trivial
- quality-c10-5: `app/services/auth_dependencies.py:14` — _make_aware contradictory type: `dt: datetime` (non-optional) but returns None; mypy error — MEDIUM, trivial
- quality-c10-6: `app/services/scheduler_config.py:28,45,60` — _get_setting_value/_effective_int/_effective_str have untyped `db` param — MEDIUM, trivial
- quality-c10-7: `app/services/file_upload.py:95` — count() missing entity_type/entity_id filters → wrong pagination total — MEDIUM, small
- quality-c10-8: `app/services/person.py:75` — People.delete() hard-deletes with db.delete() instead of soft-delete — MEDIUM, small
- quality-c10-9: `app/services/file_upload.py:102` — lazy `from sqlalchemy import func` import inside count() method — LOW, trivial
- quality-c10-10: `app/web/auth.py:78` — lazy `AuthFlow` import inside login_submit() — LOW, trivial
- quality-c10-11: `app/api/file_uploads.py:15` — upload_file is async def (CLAUDE.md sync rule violation) — LOW, small
- quality-c10-12: `app/services/query_utils.py` — no unit tests for apply_ordering/apply_pagination/validate_enum — LOW, small
- quality-c10-13: `app/services/common.py` — no unit tests for coerce_uuid/paginate — LOW, small
- quality-c10-14: `app/services/response.py` — no unit tests for list_response/ListResponseMixin — LOW, small

### OPEN API FINDINGS (api-c3, first api scan 2026-02-27)
- api-c3-1: `app/api/auth_flow.py:215` — 6 route handlers contain ORM mutations + db.commit() (update_me, upload_avatar, delete_avatar, revoke_session, revoke_all_other_sessions, change_password) — HIGH, large
- api-c3-2: `app/api/auth_flow.py:305` — 4 route handlers use db.query() (list_sessions, revoke_session, revoke_all_other_sessions, change_password) — HIGH, small
- api-c3-3: `app/schemas/auth_flow.py:69` — Two incompatible ErrorResponse schemas (auth_flow vs error.py) — MEDIUM, trivial
- api-c3-4: `app/api/scheduler.py:58` — POST /scheduler/tasks/refresh missing response_model — MEDIUM, trivial
- api-c3-5: `app/api/scheduler.py:63` — POST /scheduler/tasks/{task_id}/enqueue missing response_model — MEDIUM, trivial
- api-c3-6: `app/api/notifications.py:77` — POST /notifications/me/read-all missing response_model — MEDIUM, trivial
- api-c3-7: `app/api/notifications.py:40` — list_my_notifications total=len(items) pagination bug when unread_only=False — MEDIUM, small
- api-c3-8: `app/api/notifications.py:25` — db.commit() directly in notification + file-upload route handlers — MEDIUM, small
- api-c3-9: `app/api/notifications.py:71` — lazy HTTPException imports in function bodies (also file_uploads.py:41) — LOW, trivial
- api-c3-10: `app/api/auth.py:55` — order_by param undocumented in OpenAPI (no allowed values) across all list endpoints — LOW, trivial

### OPEN API FINDINGS (api-c7, 2026-02-27)
- api-c7-1: `app/api/billing.py:50` — billing router missing URL prefix; 52 endpoints at API root — HIGH, trivial
- api-c7-2: `app/api/ws.py:22` — `_authenticate_ws()` creates SessionLocal() directly; session not managed by DI — MEDIUM, small
- api-c7-3: `app/api/scheduler.py:65` — enqueue_scheduled_task no None check → AttributeError (500) on missing task — MEDIUM, trivial
- api-c7-4: `app/api/file_uploads.py:64` — list_file_uploads count() ignores entity_type/entity_id filters — MEDIUM, trivial
- api-c7-5: `app/api/auth.py:24` — auth router no prefix, no router-level tags; per-endpoint tags inconsistent — MEDIUM, small
- api-c7-6: `app/api/ws.py:15` — WebSocket router missing tags; endpoint invisible in OpenAPI groups — LOW, trivial
- api-c7-7: `app/api/audit.py:31` (and 20+ list endpoints) — order_by has no pattern= validation (order_dir has it) — LOW, small
- api-c7-8: `app/main.py:226` — _include_api_router registers each router twice (root + /api/v1); duplicate OpenAPI entries — LOW, small
- api-c7-9: `app/api/auth_flow.py:250` — upload_avatar is async def, violates CLAUDE.md sync route rule — LOW, small

### OPEN API FINDINGS (api-c11, 2026-02-28)
- api-c11-1: `app/main.py:269` — rbac_router only requires_user_auth; any user can manage roles/permissions — HIGH, trivial
- api-c11-2: `app/main.py:270` — people_router only requires_user_auth; any user can CRUD any person — HIGH, trivial
- api-c11-3: `app/main.py:272` — settings_router only requires_user_auth; any user can modify system settings — HIGH, trivial
- api-c11-4: `app/main.py:273` — scheduler_router only requires_user_auth; any user can manage scheduled tasks — HIGH, trivial
- api-c11-5: `app/main.py:274` — billing_router only requires_user_auth; any user can create/modify billing records — HIGH, trivial
- api-c11-6: `app/api/notifications.py:18` — POST /notifications any user can send to any recipient_id — MEDIUM, trivial
- api-c11-7: `app/api/auth_flow.py:93` — mfa_setup() has authorization check (person_id compare) in route, not service — MEDIUM, trivial
- api-c11-8: `app/schemas/auth_flow.py:97` — MeUpdateRequest.gender/preferred_contact_method untyped (str not enum); DB-level error on invalid input — MEDIUM, trivial
- api-c11-9: `app/services/auth_dependencies.py:23` — _get_db() duplicates get_db(); every authenticated request opens 2 DB sessions — MEDIUM, small
- api-c11-10: `app/api/auth_flow.py:300` — GET /auth/me/sessions loads all sessions with no LIMIT — LOW, trivial

### Key API Architecture Note
`app/api/auth_flow.py` is a THICK CONTROLLER — it was not written as a thin wrapper. It contains direct ORM manipulation, password hashing, session mutation, and db.commit() calls that belong in app/services/. Different from app/services/auth_flow.py which has the quality-c2 db.query() and db.commit() issues in the service layer.

### Authorization Pattern (confirmed 2026-02-28)
`require_role("admin")` is correctly applied only to `auth_router` (line 267). Five other routers (rbac, people, settings, scheduler, billing) use only `require_user_auth` — any JWT holder can access all admin operations. The `require_role` factory in auth_dependencies.py is properly implemented and works correctly — just not applied to these routers.

### OPEN DEPS FINDINGS (deps-c4, 2026-02-27 cycle 4)
- deps-c4-1: `app/api/` — missing `__init__.py` (namespace pkg vs regular pkg) — MEDIUM, trivial
- deps-c4-2: `app/schemas/` — missing `__init__.py` — MEDIUM, trivial
- deps-c4-3: `app/services/storage.py:102` — `boto3` imported but not in pyproject.toml — MEDIUM, trivial
- deps-c4-4: `pyproject.toml:29` — passlib 1.7.4 crashes at import with bcrypt >= 4.0 (AttributeError: no `__about__`); fix: pin `bcrypt = "<4.0"` — MEDIUM, trivial
- deps-c4-5: `app/services/auth.py:12` — split `from app.models.auth import` across two blocks; ruff/isort lint fail — LOW, trivial
- deps-c4-6: `pyproject.toml:33` — `types-redis` missing from dev deps; mypy treats all redis calls as Any — LOW, trivial
- deps-c4-7: `app/main.py:303` — `RedirectResponse` imported inside function body rather than at module level — LOW, trivial

### OPEN DEPS FINDINGS (deps-c8, 2026-02-28 cycle 8)
- deps-c8-1: project root — no `.python-version` file; pyenv/asdf defaults to system Python 3.10, blocking poetry install — MEDIUM, trivial
- deps-c8-2: `pytest.ini:11` — `crypt` deprecation warning suppressed; passlib uses removed-in-3.13 `crypt` module; Python 3.13 risk masked — MEDIUM, medium
- deps-c8-3: `pyproject.toml` — `python-multipart` not explicitly pinned; 0.0.22 emits PendingDeprecationWarning (old `multipart` module name) suppressed in pytest.ini:10 — LOW, trivial
- deps-c8-4: `pyproject.toml:37` — `ruff = ">=0.15.0"` and `mypy = ">=1.11"` unbounded; breaking version could land silently on poetry update — LOW, trivial
- deps-c8-5: `pyproject.toml:33` — `types-passlib` missing from dev deps; passlib calls in auth_flow.py untyped (same pattern as deps-c4-6) — LOW, trivial

### OPEN DEPS FINDINGS (deps-c12, 2026-02-28 cycle 12)
- deps-c12-1: `pyproject.toml:9` — `python = ">=3.11,<3.13"` blocks Python 3.13 (GA Oct 2024); Dockerfile uses python:3.12-slim — MEDIUM, trivial
- deps-c12-2: `app/services/scheduler.py:96` — `from app.celery_app import celery_app` inline in enqueue_task(); no circular import exists — LOW, trivial
- deps-c12-3: `app/main.py:339` — `import redis as redis_lib` inline in readiness_check() (distinct from deps-c4-7 at line 303) — LOW, trivial
- deps-c12-4: `app/web/settings.py:130` — `import json` inline inside conditional branch in update_setting() — LOW, trivial

**Inline imports confirmed intentional (do NOT flag):**
- `app/middleware/rate_limit.py:99` — `import redis` inside `_get_redis()`: intentional, catches ImportError for graceful degradation
- `app/telemetry.py:13-23` — OTel imports inside `setup_otel()`: conditional on OTEL_ENABLED env var

### OPEN DEPS FINDINGS (deps-audit, 2026-02-27 — all still open, fixes did not land)
- deps-1: python-jose 3.3.0 CVE-2024-33663 (algorithm confusion) — HIGH, medium effort
- deps-2: Jinja2 3.1.4 CVE-2024-56201/56326 — HIGH, trivial
- deps-3: cryptography 42.x → 46.x (security patches) — MEDIUM, small
- deps-4: passlib abandoned + bcrypt compat — MEDIUM, medium effort
- deps-5: fastapi 0.111.0 stale (→ 0.115.x) — MEDIUM, small
- deps-6: otel-instrumentation 0.47b0 beta — MEDIUM, small
- deps-7–11: uvicorn/httpx/pydantic/dotenv/celery minor bumps — LOW, trivial

## Scan History

| Date       | Type     | Cycle  | Findings | Health |
|------------|----------|--------|----------|--------|
| 2026-02-27 | security | cycle1 (pass 1) | 15 (1C/5H/5M/4L) | 72/100 |
| 2026-02-27 | security | cycle1 (pass 2) | 16 (1C/5H/7M/3L) | 68/100 |
| 2026-02-27 | security | cycle1 (pass 3) | 5 new (0C/0H/4M/1L) | 82/100 |
| 2026-02-27 | quality  | cycle2           | 9 new (1C/2H/4M/2L) | 71/100 |
| 2026-02-27 | api      | cycle3           | 10 new (0C/2H/6M/2L) | 68/100 |
| 2026-02-27 | deps     | cycle4           | 7 new (0C/0H/4M/3L) | 62/100 deps |
| 2026-02-27 | security | cycle5           | 6 new (0C/2H/4M/0L) | 65/100 |
| 2026-02-27 | api      | cycle7           | 9 new (0C/1H/4M/4L) | 56/100 |
| 2026-02-28 | deps     | cycle8           | 5 new (0C/2M/3L) | 54/100 deps |
| 2026-02-28 | security | cycle9           | 5 new (0C/1H/1M/3L) | 50/100 |
| 2026-02-28 | quality  | cycle10          | 14 new (0C/2H/6M/6L) | 46/100 |
| 2026-02-28 | api      | cycle11          | 10 new (0C/5H/4M/1L) | 40/100 api |
| 2026-02-28 | deps     | cycle12          | 4 new (0C/0H/1M/3L) | 52/100 deps |

## Recurring Issues

- **aider/deepseek commits spurious files**: The aider engine (deepseek-chat) has committed `.agent-run.sh` (the 350-line spawn script with hardcoded /home/dotmac/ paths) in multiple PRs alongside legitimate fixes. Add explicit "modify ONLY <file>, do NOT create any other files" to task descriptions for aider agents doing single-file edits.
- **Fix pipeline execution gaps**: PRs claimed to fix c1-2 and c1-3 were merged but the actual code changes were NOT applied to the target files. Before marking a finding as fixed, Sentinel must verify by reading the source file, not just trusting PR descriptions or memory entries.
- **`| safe` on `tojson` fixed**: audit/detail.html and billing/webhook_events/detail.html `| safe` removed in PR #2 (c1-5 and c1-6, both confirmed fixed by reading files 2026-02-27).
- `.gitignore` now includes `.aider*`, `.seabone/` runtime dirs, and `.worktrees/` (committed 2026-02-27).

