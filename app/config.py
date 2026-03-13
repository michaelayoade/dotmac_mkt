import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5439/dotmac_mkt",
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    secret_key: str = os.getenv("SECRET_KEY", "")
    db_pool_size: int = int(os.getenv("DB_POOL_SIZE", "5"))
    db_max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    db_pool_timeout: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    db_pool_recycle: int = int(os.getenv("DB_POOL_RECYCLE", "1800"))

    # Avatar settings
    avatar_upload_dir: str = os.getenv("AVATAR_UPLOAD_DIR", "static/avatars")
    avatar_max_size_bytes: int = int(
        os.getenv("AVATAR_MAX_SIZE_BYTES", str(2 * 1024 * 1024))
    )  # 2MB
    avatar_allowed_types: str = os.getenv(
        "AVATAR_ALLOWED_TYPES", "image/jpeg,image/png,image/gif,image/webp"
    )
    avatar_url_prefix: str = os.getenv("AVATAR_URL_PREFIX", "/static/avatars")

    # Branding
    brand_name: str = os.getenv("BRAND_NAME", "DotMac Marketing")
    brand_tagline: str = os.getenv("BRAND_TAGLINE", "Marketing & Digital Asset Management")
    brand_logo_url: str | None = os.getenv("BRAND_LOGO_URL") or None
    branding_upload_dir: str = os.getenv("BRANDING_UPLOAD_DIR", "static/branding")
    branding_max_size_bytes: int = int(
        os.getenv("BRANDING_MAX_SIZE_BYTES", str(5 * 1024 * 1024))
    )  # 5MB
    branding_allowed_types: str = os.getenv(
        "BRANDING_ALLOWED_TYPES",
        "image/jpeg,image/png,image/gif,image/webp,image/svg+xml,image/x-icon,image/vnd.microsoft.icon",
    )
    branding_url_prefix: str = os.getenv("BRANDING_URL_PREFIX", "/static/branding")

    # Storage
    storage_backend: str = os.getenv("STORAGE_BACKEND", "local")  # "local" or "s3"
    storage_local_dir: str = os.getenv("STORAGE_LOCAL_DIR", "static/uploads")
    storage_url_prefix: str = os.getenv("STORAGE_URL_PREFIX", "/static/uploads")
    s3_bucket: str = os.getenv("S3_BUCKET", "")
    s3_region: str = os.getenv("S3_REGION", "")
    s3_access_key: str = os.getenv("S3_ACCESS_KEY", "")
    s3_secret_key: str = os.getenv("S3_SECRET_KEY", "")
    s3_endpoint_url: str = os.getenv("S3_ENDPOINT_URL", "")

    # File uploads
    upload_max_size_bytes: int = int(
        os.getenv("UPLOAD_MAX_SIZE_BYTES", str(10 * 1024 * 1024))
    )  # 10MB
    upload_allowed_types: str = os.getenv(
        "UPLOAD_ALLOWED_TYPES",
        "image/jpeg,image/png,image/gif,image/webp,application/pdf,text/plain,text/csv",
    )

    # CORS
    cors_origins: str = os.getenv("CORS_ORIGINS", "")  # Comma-separated origins

    # Channel OAuth & Encryption
    encryption_key: str = os.getenv("ENCRYPTION_KEY", "")
    meta_app_id: str = os.getenv("META_APP_ID", "")
    meta_app_secret: str = os.getenv("META_APP_SECRET", "")
    twitter_client_id: str = os.getenv("TWITTER_CLIENT_ID", "")
    twitter_client_secret: str = os.getenv("TWITTER_CLIENT_SECRET", "")
    linkedin_client_id: str = os.getenv("LINKEDIN_CLIENT_ID", "")
    linkedin_client_secret: str = os.getenv("LINKEDIN_CLIENT_SECRET", "")
    google_ads_client_id: str = os.getenv("GOOGLE_ADS_CLIENT_ID", "")
    google_ads_client_secret: str = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "")
    google_ads_developer_token: str = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    google_analytics_client_id: str = os.getenv("GOOGLE_ANALYTICS_CLIENT_ID", "")
    google_analytics_client_secret: str = os.getenv(
        "GOOGLE_ANALYTICS_CLIENT_SECRET", ""
    )

    # Google Drive
    google_drive_client_id: str = os.getenv("GOOGLE_DRIVE_CLIENT_ID", "")
    google_drive_client_secret: str = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET", "")
    google_drive_folder_id: str = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

    # CRM Bridge
    crm_base_url: str = os.getenv("CRM_BASE_URL", "")
    crm_api_key: str = os.getenv("CRM_API_KEY", "")

    # Metrics
    metrics_token: str | None = os.getenv("METRICS_TOKEN") or None


def validate_settings(s: Settings) -> list[str]:
    """Validate required settings at startup. Returns list of warnings."""
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

    if not s.secret_key:
        warnings.append("SECRET_KEY is not set — CSRF and session security weakened")

    if (
        "localhost" in s.database_url
        and os.getenv("ENVIRONMENT", "dev") == "production"
    ):
        warnings.append("DATABASE_URL points to localhost in production")

    return warnings


settings = Settings()
