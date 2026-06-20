from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _first_present_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _default_app_base_url() -> str:
    explicit = _first_present_env("SCHOOL_PLATFORM_APP_BASE_URL", "APP_BASE_URL", "RENDER_EXTERNAL_URL")
    if explicit:
        return explicit.rstrip("/")
    render_host = _first_present_env("RENDER_EXTERNAL_HOSTNAME")
    if render_host:
        return f"https://{render_host}".rstrip("/")
    return "http://127.0.0.1:8011"


@dataclass(slots=True)
class SchoolPlatformSettings:
    storage_backend: str = "json"
    json_path: str = "data/school_platform_store.json"
    postgres_dsn: str | None = None
    app_base_url: str = "http://127.0.0.1:8011"
    payment_provider: str = "mock"
    payment_currency: str = "jpy"
    stripe_secret_key: str | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_success_url: str | None = None
    stripe_cancel_url: str | None = None
    stripe_webhook_tolerance_seconds: int = 300
    email_provider: str = "mock"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True
    resend_api_key: str | None = None
    resend_from_email: str | None = None
    resend_reply_to_email: str | None = None
    line_channel_access_token: str | None = None
    line_channel_secret: str | None = None
    line_fallback_user_id: str | None = None
    line_api_base_url: str = "https://api.line.me"
    notification_test_email: str | None = None
    notification_test_line_user_id: str | None = None


def load_settings() -> SchoolPlatformSettings:
    return SchoolPlatformSettings(
        storage_backend=os.getenv("SCHOOL_PLATFORM_STORAGE_BACKEND", "json").strip().lower(),
        json_path=os.getenv("SCHOOL_PLATFORM_JSON_PATH", "data/school_platform_store.json").strip(),
        postgres_dsn=_first_present_env("SCHOOL_PLATFORM_POSTGRES_DSN", "DATABASE_URL"),
        app_base_url=_default_app_base_url(),
        payment_provider=os.getenv("SCHOOL_PLATFORM_PAYMENT_PROVIDER", "mock").strip().lower(),
        payment_currency=os.getenv("SCHOOL_PLATFORM_PAYMENT_CURRENCY", "jpy").strip().lower(),
        stripe_secret_key=os.getenv("SCHOOL_PLATFORM_STRIPE_SECRET_KEY"),
        stripe_publishable_key=os.getenv("SCHOOL_PLATFORM_STRIPE_PUBLISHABLE_KEY"),
        stripe_webhook_secret=os.getenv("SCHOOL_PLATFORM_STRIPE_WEBHOOK_SECRET"),
        stripe_success_url=os.getenv("SCHOOL_PLATFORM_STRIPE_SUCCESS_URL"),
        stripe_cancel_url=os.getenv("SCHOOL_PLATFORM_STRIPE_CANCEL_URL"),
        stripe_webhook_tolerance_seconds=int(os.getenv("SCHOOL_PLATFORM_STRIPE_WEBHOOK_TOLERANCE_SECONDS", "300")),
        email_provider=os.getenv("SCHOOL_PLATFORM_EMAIL_PROVIDER", "mock").strip().lower(),
        smtp_host=os.getenv("SCHOOL_PLATFORM_SMTP_HOST"),
        smtp_port=int(os.getenv("SCHOOL_PLATFORM_SMTP_PORT", "587")),
        smtp_username=os.getenv("SCHOOL_PLATFORM_SMTP_USERNAME"),
        smtp_password=os.getenv("SCHOOL_PLATFORM_SMTP_PASSWORD"),
        smtp_from_email=os.getenv("SCHOOL_PLATFORM_SMTP_FROM_EMAIL"),
        smtp_use_tls=os.getenv("SCHOOL_PLATFORM_SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"},
        resend_api_key=os.getenv("SCHOOL_PLATFORM_RESEND_API_KEY"),
        resend_from_email=os.getenv("SCHOOL_PLATFORM_RESEND_FROM_EMAIL"),
        resend_reply_to_email=os.getenv("SCHOOL_PLATFORM_RESEND_REPLY_TO_EMAIL"),
        line_channel_access_token=os.getenv("SCHOOL_PLATFORM_LINE_CHANNEL_ACCESS_TOKEN", os.getenv("LINE_CHANNEL_ACCESS_TOKEN")),
        line_channel_secret=os.getenv("SCHOOL_PLATFORM_LINE_CHANNEL_SECRET", os.getenv("LINE_CHANNEL_SECRET")),
        line_fallback_user_id=os.getenv("SCHOOL_PLATFORM_LINE_FALLBACK_USER_ID"),
        line_api_base_url=os.getenv("SCHOOL_PLATFORM_LINE_API_BASE_URL", "https://api.line.me").rstrip("/"),
        notification_test_email=_first_present_env("SCHOOL_PLATFORM_NOTIFICATION_TEST_EMAIL", "SCHOOL_PLATFORM_SMTP_FROM_EMAIL"),
        notification_test_line_user_id=_first_present_env("SCHOOL_PLATFORM_NOTIFICATION_TEST_LINE_USER_ID", "SCHOOL_PLATFORM_LINE_FALLBACK_USER_ID"),
    )
