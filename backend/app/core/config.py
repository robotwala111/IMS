"""
Application Configuration Module

Provides centralized configuration management using Pydantic Settings.
All configuration is loaded from environment variables with sensible defaults.

Usage:
    from app.core.config import settings
    print(settings.APP_NAME)
"""

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "ScienceTech-IMS"
    APP_URL: str = "http://localhost:8000"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_HOSTS: List[str] = ["localhost", "127.0.0.1"]
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:3000",
        "https://amirotechsolutions.com",
        "https://www.amirotechsolutions.com",
    ]

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:change-me@localhost:5432/ndt_ims"
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_CONNECT_TIMEOUT_SECONDS: int = 10
    DATABASE_COMMAND_TIMEOUT_SECONDS: int = 30

    # JWT Authentication
    JWT_SECRET_KEY: str = "your-super-secret-jwt-key-change-in-production-min-32-chars"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # File Storage
    STORAGE_TYPE: str = "local"
    STORAGE_LOCAL_PATH: str = "./data/files"
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_FILE_TYPES: List[str] = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".png", ".jpg", ".jpeg"]

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    LOG_FILE_PATH: str = ""

    # Email
    EMAIL_ENABLED: bool = False
    EMAIL_BACKEND: str = "console"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str = "noreply@sciencetech-ims.local"
    SMTP_FROM_NAME: str = "ScienceTech-IMS"
    LOW_STOCK_ALERT_EMAILS: List[str] = []

    # Public demo request email (locked-module enquiry form)
    DEMO_REQUEST_ADMIN_EMAIL: str = "amirotechsolutions.sales@gmail.com"
    DEMO_REQUEST_EMAIL_ENABLED: bool = False

    # Scheduled IMS demo (Google Calendar + Meet)
    GOOGLE_CALENDAR_CLIENT_ID: str = ""
    GOOGLE_CALENDAR_CLIENT_SECRET: str = ""
    GOOGLE_CALENDAR_REFRESH_TOKEN: str = ""
    GOOGLE_CALENDAR_ID: str = "amirotechsolutions.sales@gmail.com"
    DEMO_BOOKING_ADMIN_EMAIL: str = "amirotechsolutions.sales@gmail.com"
    DEMO_BOOKING_TIMEZONE: str = "Asia/Kolkata"
    DEMO_BOOKING_START_HOUR: int = 10
    DEMO_BOOKING_END_HOUR: int = 17
    DEMO_BOOKING_DURATION_MINUTES: int = 30
    DEMO_BOOKING_DAYS_AHEAD: int = 90
    DEMO_BOOKING_EMAIL_ENABLED: bool = False

    # Archive & Data Retention
    ARCHIVE_RETENTION_MONTHS: int = 3
    ARCHIVE_WARNING_DAYS: int = 5
    ARCHIVE_RECIPIENT_EMAILS: List[str] = []  # GM/CEO emails; falls back to ADMIN/HEAD_OFFICE_MANAGER users
    ARCHIVE_EMAIL_ATTACHMENTS_ENABLED: bool = False
    GENERATED_DOCUMENT_RETENTION_DAYS: int = 5
    MONTHLY_DOCUMENT_ZIP_MAX_MB: int = 20
    GENERATED_DOCUMENT_PREFER_PDF: bool = False
    GENERATED_DOCUMENT_CRON_SECRET: str = ""

    # Scheduler
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TIMEZONE: str = "UTC"
    VISION_CERTIFICATE_ALERT_DAYS: int = 15
    VISION_CERTIFICATE_REMINDER_INTERVAL_HOURS: int = 24
    REGISTER_EMAIL_INTERVAL_DAYS: int = 30

    # Alert Thresholds
    EXPIRY_ALERT_DAYS: int = 45
    CALIBRATION_ALERT_DAYS: int = 15
    LOW_STOCK_CHECK_INTERVAL_HOURS: int = 4
    LOW_STOCK_CRON_SECRET: str = ""

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 300
    RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE: int = 30

    # Security
    PASSWORD_MIN_LENGTH: int = 8
    SESSION_TIMEOUT_MINUTES: int = 480
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 15
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    AUDIT_INTEGRITY_KEY: str = ""

    # Local startup controls
    AUTO_CREATE_TABLES: bool = False
    CREATE_DEFAULT_ADMIN: bool = False
    DEFAULT_ADMIN_EMAIL: str = "admin@ndt.com"
    DEFAULT_ADMIN_PASSWORD: str = "Admin@123"
    DEMO_USER_EMAIL: str = "demo.amiro@gmail.com"

    @field_validator("CORS_ORIGINS", "ALLOWED_HOSTS", "ALLOWED_FILE_TYPES", "LOW_STOCK_ALERT_EMAILS", "ARCHIVE_RECIPIENT_EMAILS", mode="before")
    @classmethod
    def parse_list(cls, v: str | List[str]) -> List[str]:
        """Parse comma-separated string or JSON list into Python list."""
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [i.strip() for i in v.split(",") if i.strip()]
        return v

    @field_validator("GOOGLE_CALENDAR_REFRESH_TOKEN", "GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET", mode="before")
    @classmethod
    def clean_google_creds(cls, v: str) -> str:
        """Strip all accidental whitespace/newlines from Google OAuth credentials."""
        if isinstance(v, str):
            return "".join(v.split())
        return v

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, v: str | bool) -> bool:
        """Accept common environment labels in DEBUG for older deployments."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in {"1", "true", "yes", "on", "dev", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return bool(v)

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV.lower() == "development"

    @property
    def is_testing(self) -> bool:
        return self.APP_ENV.lower() == "testing"

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
