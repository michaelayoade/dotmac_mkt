# DotMac Marketing — Claude Agent Guide

FastAPI + SQLAlchemy 2.0 + Jinja2/HTMX/Alpine.js + PostgreSQL. Marketing & digital asset management app.
Port 8009 (external) → 8001 (internal). Cloned from dotmac_starter.

## Non-Negotiable Rules
- SQLAlchemy 2.0: `select()` + `scalars()`, never `db.query()`
- `db.flush()` in services, NOT `db.commit()` — routes commit
- Routes are thin wrappers — no business logic inside
- SQLite in-memory for tests
- Commands: always `poetry run ruff`, `poetry run mypy`, `poetry run pytest`

## Domain Model
- **Campaign** — central organizing unit (draft/active/paused/completed/archived)
- **Asset** — media files backed by Google Drive (image/video/document/template/brand_guide)
- **Channel** — connected marketing channel with encrypted OAuth credentials
- **Post** — planned content linked to campaign + channel (draft/planned in Phase 1)
- **Task** — team coordination item within a campaign (todo/in_progress/done)
- **ChannelMetric** — analytics data with partial unique indexes for upsert

## Channel Adapters
- Base: `app/adapters/base.py` (ChannelAdapter ABC)
- Providers: meta, twitter, linkedin, google_ads, google_analytics
- Registry: `app/adapters/registry.py` → `get_adapter(provider, **kwargs)`
- Credentials: Fernet encryption via `CredentialService` (ENCRYPTION_KEY env var)

## Template Rules (same as ERP)
- Single quotes on `x-data` with `tojson`
- `{{ var if var else '' }}` not `{{ var | default('') }}`
- Dict lookup for dynamic Tailwind classes
- `| safe` only for CSRF, `tojson`, admin CSS
- `status_badge()`, `empty_state()`, `live_search()` macros — never inline
- Every `{% for %}` needs `{% else %}` + `empty_state()`
- CSRF mandatory on every POST form
- `<div id="results-container">` on list pages
- `scope="col"` on all `<th>`
- Dark mode: always pair `bg-white dark:bg-slate-800`

## Service Pattern
```python
class SomeService:
    def __init__(self, db: Session):
        self.db = db
    def create(self, data) -> Model:
        record = Model(**data.model_dump())
        self.db.add(record)
        self.db.flush()
        return record
```

## Key Environment Variables
- `DATABASE_URL` — PostgreSQL connection (default: dotmac_mkt on port 5439)
- `ENCRYPTION_KEY` — Fernet key for OAuth token encryption
- `META_APP_ID`, `META_APP_SECRET` — Meta/Facebook/Instagram
- `TWITTER_CLIENT_ID`, `TWITTER_CLIENT_SECRET` — X/Twitter
- `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` — LinkedIn
- `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_DEVELOPER_TOKEN` — Google Ads
- `GOOGLE_ANALYTICS_CLIENT_ID`, `GOOGLE_ANALYTICS_CLIENT_SECRET` — GA4
- `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, `GOOGLE_DRIVE_FOLDER_ID` — Drive
- `CRM_BASE_URL`, `CRM_API_KEY` — dotmac_crm integration

## Celery Tasks
- `analytics_sync` — daily, pulls 7 days of metrics per connected channel
- `token_refresh` — every 30 min, refreshes tokens expiring within 10 min
- `drive_sync` — hourly, indexes files from Google Drive marketing folder

## Security
- Never bare `except:`
- Never `| safe` on user content
- OAuth tokens encrypted at rest via Fernet
- File uploads via `FileUploadService` only
- `resolve_safe_path()` for all path operations
