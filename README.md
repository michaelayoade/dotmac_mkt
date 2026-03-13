# Starter Template

A production-ready FastAPI starter template with enterprise-grade features including authentication, RBAC, audit logging, background jobs, and full observability.

## Features

- **Authentication & Security**
  - JWT-based authentication with refresh token rotation
  - Multi-factor authentication (TOTP, SMS, Email)
  - API key management with rate limiting
  - Session management with token hashing
  - Password policies and account lockout

- **Authorization**
  - Role-based access control (RBAC)
  - Fine-grained permissions system
  - Scope-based API access

- **Audit & Compliance**
  - Comprehensive audit logging
  - Request/response tracking
  - Actor and IP address logging

- **Background Jobs**
  - Celery workers with Redis broker
  - Database-backed Beat scheduler
  - Persistent scheduled tasks

- **Observability**
  - Prometheus metrics
  - OpenTelemetry distributed tracing
  - Structured JSON logging

- **Web UI**
  - Jinja2 server-side rendering
  - Static file serving
  - Avatar upload handling

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI 0.111.0 |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Cache/Broker | Redis 7 |
| Task Queue | Celery 5.4 |
| Auth | python-jose, passlib, pyotp |
| Tracing | OpenTelemetry |
| Metrics | Prometheus |

## Project Structure

```
├── app/
│   ├── api/              # Route handlers
│   ├── models/           # SQLAlchemy ORM models
│   ├── schemas/          # Pydantic validation schemas
│   ├── services/         # Business logic layer
│   ├── tasks/            # Celery background tasks
│   ├── main.py           # FastAPI app initialization
│   ├── config.py         # Application settings
│   ├── db.py             # Database configuration
│   ├── celery_app.py     # Celery configuration
│   └── telemetry.py      # OpenTelemetry setup
├── templates/            # Jinja2 HTML templates
├── static/               # Static assets
├── alembic/              # Database migrations
├── scripts/              # Utility scripts
├── tests/                # Test suite
├── docker-compose.yml    # Container orchestration
└── Dockerfile            # Container image
```

## Getting Started

### Prerequisites

- Python 3.11 or 3.12
- PostgreSQL 16
- Redis 7
- [Poetry](https://python-poetry.org/) (recommended) or pip

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd starter_template
   ```

2. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Install dependencies**
   ```bash
   # Using Poetry (recommended)
   poetry install

   # Or using pip
   pip install -r requirements.txt
   ```

### Running with Docker (Recommended)

The easiest way to run the application is with Docker Compose:

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f app

# Stop all services
docker compose down
```

Services:
- **App**: http://localhost:8001
- **PostgreSQL**: localhost:5434
- **Redis**: localhost:6379

### Running Locally

1. **Start PostgreSQL and Redis** (or use Docker for just the databases)
   ```bash
   docker compose up -d db redis
   ```

2. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

3. **Seed initial data**
   ```bash
   # Initialize RBAC roles and permissions
   python scripts/seed_rbac.py

   # Create admin user
   python scripts/seed_admin.py --username admin --password <password>

   # Sync settings
   python scripts/settings_sync.py
   ```

4. **Start the application**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
   ```

5. **Start Celery worker** (in a separate terminal)
   ```bash
   celery -A app.celery_app worker -l info
   ```

6. **Start Celery Beat scheduler** (in a separate terminal)
   ```bash
   celery -A app.celery_app beat -l info
   ```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg://postgres:postgres@localhost:5434/starter_template` |
| `REDIS_URL` | Redis connection string | `redis://:redis@localhost:6379/0` |
| `CELERY_BROKER_URL` | Celery broker URL | `redis://:redis@localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery result backend | `redis://:redis@localhost:6379/1` |
| `JWT_SECRET` | JWT signing secret | Required |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `JWT_ACCESS_TTL_MINUTES` | Access token TTL | `15` |
| `JWT_REFRESH_TTL_DAYS` | Refresh token TTL | `30` |
| `TOTP_ISSUER` | TOTP issuer name | `starter_template` |
| `TOTP_ENCRYPTION_KEY` | TOTP secret encryption key | Required |
| `OTEL_ENABLED` | Enable OpenTelemetry | `false` |
| `OTEL_SERVICE_NAME` | Service name for tracing | `starter_template` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint | - |

### OpenBao Integration

Secrets can be resolved from OpenBao by using the `openbao://` prefix:

```bash
JWT_SECRET=openbao://secret/data/starter_template#jwt_secret
```

Configure OpenBao connection:
```bash
OPENBAO_ADDR=https://vault.example.com
OPENBAO_TOKEN=<token>
OPENBAO_NAMESPACE=<namespace>
OPENBAO_KV_VERSION=2
```

## API Endpoints

### Authentication (`/auth`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | User login |
| POST | `/auth/refresh` | Refresh access token |
| POST | `/auth/logout` | Logout and revoke session |
| GET | `/auth/me` | Get current user profile |
| PUT | `/auth/me` | Update current user profile |
| POST | `/auth/password-change` | Change password |
| POST | `/auth/password-reset-request` | Request password reset |
| POST | `/auth/password-reset` | Complete password reset |
| POST | `/auth/mfa/setup` | Setup MFA |
| POST | `/auth/mfa/verify` | Verify MFA code |
| GET | `/auth/sessions` | List user sessions |
| DELETE | `/auth/sessions/{id}` | Revoke session |

### People (`/people`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/people` | Create person |
| GET | `/people` | List people |
| GET | `/people/{id}` | Get person |
| PUT | `/people/{id}` | Update person |
| DELETE | `/people/{id}` | Delete person |

### RBAC (`/roles`, `/permissions`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/roles` | Create role |
| GET | `/roles` | List roles |
| PUT | `/roles/{id}` | Update role |
| DELETE | `/roles/{id}` | Delete role |
| POST | `/permissions` | Create permission |
| GET | `/permissions` | List permissions |

### Monitoring

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/metrics` | Prometheus metrics |

## Development

### Code Style

The project follows standard Python conventions with:
- Type hints throughout
- Pydantic for data validation
- SQLAlchemy 2.0 mapped column syntax

### Adding New Endpoints

1. Create model in `app/models/`
2. Create schemas in `app/schemas/`
3. Implement service logic in `app/services/`
4. Add route handlers in `app/api/`
5. Register router in `app/main.py`

### Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_auth_flow.py
```

## Scripts

| Script | Description |
|--------|-------------|
| `scripts/seed_admin.py` | Create admin user |
| `scripts/seed_rbac.py` | Initialize roles and permissions |
| `scripts/settings_sync.py` | Sync settings with database |
| `scripts/settings_validate.py` | Validate settings configuration |

## License

[Add your license here]
