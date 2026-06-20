from __future__ import annotations

from email.message import EmailMessage
from email.utils import parseaddr
from html import escape
import smtplib
from typing import Any
from uuid import uuid4

import httpx

from school_platform.config import SchoolPlatformSettings, load_settings

RESERVED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "invalid",
    "localhost",
    "local",
    "test",
}
RESERVED_EMAIL_SUFFIXES = (
    ".example",
    ".invalid",
    ".localhost",
    ".local",
    ".test",
)


class SchoolPlatformNotificationRuntime:
    def __init__(self, settings: SchoolPlatformSettings | None = None) -> None:
        self.settings = settings or load_settings()

    def status(self) -> dict[str, Any]:
        email_provider = self._active_email_provider()
        email_blockers: list[str] = []
        if email_provider == "smtp":
            if not self.settings.smtp_host:
                email_blockers.append("missing smtp host")
            if not self.settings.smtp_from_email:
                email_blockers.append("missing smtp from email")
        elif email_provider == "resend":
            if not self.settings.resend_api_key:
                email_blockers.append("missing resend api key")
            if not self.settings.resend_from_email:
                email_blockers.append("missing resend from email")
        email_ready = email_provider == "mock" or (
            email_provider == "smtp" and bool(self.settings.smtp_host and self.settings.smtp_from_email)
        ) or (
            email_provider == "resend" and bool(self.settings.resend_api_key and self.settings.resend_from_email)
        )
        line_blockers: list[str] = []
        if not self.settings.line_channel_access_token:
            line_blockers.append("missing line channel access token")
        line_ready = bool(self.settings.line_channel_access_token)
        line_webhook_ready = bool(self.settings.line_channel_access_token and self.settings.line_channel_secret)
        return {
            "email_provider": email_provider,
            "email_ready": email_ready,
            "email_live_mode": email_provider != "mock" and email_ready,
            "email_blockers": email_blockers,
            "smtp_host_present": bool(self.settings.smtp_host),
            "smtp_from_email_present": bool(self.settings.smtp_from_email),
            "smtp_username_present": bool(self.settings.smtp_username),
            "smtp_password_present": bool(self.settings.smtp_password),
            "smtp_port": self.settings.smtp_port,
            "smtp_use_tls": self.settings.smtp_use_tls,
            "resend_api_key_present": bool(self.settings.resend_api_key),
            "resend_from_email_present": bool(self.settings.resend_from_email),
            "line_ready": line_ready,
            "line_live_mode": line_ready,
            "line_webhook_ready": line_webhook_ready,
            "line_blockers": line_blockers,
            "line_channel_access_token_present": bool(self.settings.line_channel_access_token),
            "line_channel_secret_present": bool(self.settings.line_channel_secret),
            "line_fallback_user_id_present": bool(self.settings.line_fallback_user_id),
            "line_targeting_mode": "fallback_user" if self.settings.line_fallback_user_id else "per_notification_recipient",
            "line_api_base_url": self.settings.line_api_base_url,
            "notification_test_email_present": bool(self.settings.notification_test_email),
            "notification_test_line_user_id_present": bool(self.settings.notification_test_line_user_id),
            "demo_email_guardrail_enabled": True,
            "message": self._status_message(email_provider, email_ready, line_ready),
        }

    def _status_message(self, email_provider: str, email_ready: bool, line_ready: bool) -> str:
        email_label = f"{email_provider}:{'ready' if email_ready else 'not_ready'}"
        line_label = f"line:{'ready' if line_ready else 'not_ready'}"
        return f"Email {email_label} / LINE {line_label}"

    def _active_email_provider(self) -> str:
        provider = self.settings.email_provider
        if provider == "auto":
            if self.settings.resend_api_key and self.settings.resend_from_email:
                return "resend"
            if self.settings.smtp_host and self.settings.smtp_from_email:
                return "smtp"
            return "mock"
        return provider

    @staticmethod
    def email_suppression_reason(recipient: str | None) -> str | None:
        if not recipient:
            return None
        _, parsed = parseaddr(recipient)
        email = parsed.strip().lower()
        if not email or "@" not in email:
            return None
        _, _, domain = email.rpartition("@")
        if not domain:
            return None
        if domain in RESERVED_EMAIL_DOMAINS or domain.endswith(RESERVED_EMAIL_SUFFIXES):
            return "Reserved/demo email address suppressed; no external delivery was attempted."
        return None

    def dispatch(
        self,
        *,
        channel: str,
        title: str,
        content: str,
        recipient: str | None,
        user_email: str | None,
    ) -> dict[str, Any]:
        if channel == "in_app":
            return {
                "status": "sent",
                "provider": "in_app",
                "provider_message_id": None,
                "error_message": None,
                "external_recipient": recipient,
            }
        if channel == "email":
            return self._dispatch_email(title=title, content=content, recipient=recipient or user_email)
        if channel == "line":
            return self._dispatch_line(title=title, content=content, recipient=recipient or self.settings.line_fallback_user_id)
        return {
            "status": "failed",
            "provider": "unsupported",
            "provider_message_id": None,
            "error_message": f"Unsupported channel: {channel}",
            "external_recipient": recipient,
        }

    def _dispatch_email(self, *, title: str, content: str, recipient: str | None) -> dict[str, Any]:
        provider = self._active_email_provider()
        if not recipient:
            return {
                "status": "failed",
                "provider": provider,
                "provider_message_id": None,
                "error_message": "Missing email recipient.",
                "external_recipient": None,
            }
        suppression_reason = self.email_suppression_reason(recipient)
        if suppression_reason:
            return {
                "status": "suppressed",
                "provider": "guardrail",
                "provider_message_id": None,
                "error_message": suppression_reason,
                "external_recipient": recipient,
            }
        if provider == "mock":
            return {
                "status": "queued",
                "provider": "mock",
                "provider_message_id": None,
                "error_message": "Email provider is mock; no external delivery was attempted.",
                "external_recipient": recipient,
            }
        if provider == "resend":
            headers = {
                "Authorization": f"Bearer {self.settings.resend_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "JapanLifeLanguageSchoolOS/1.0",
            }
            payload = {
                "from": self.settings.resend_from_email,
                "to": [recipient],
                "subject": title,
                "text": content,
                "html": self._render_email_html(title, content),
            }
            if self.settings.resend_reply_to_email:
                payload["reply_to"] = [self.settings.resend_reply_to_email]
            try:
                response = httpx.post("https://api.resend.com/emails", headers=headers, json=payload, timeout=30.0)
                response.raise_for_status()
                body = response.json()
                return {
                    "status": "sent",
                    "provider": "resend",
                    "provider_message_id": body.get("id"),
                    "error_message": None,
                    "external_recipient": recipient,
                }
            except (httpx.HTTPError, ValueError) as exc:
                return {
                    "status": "failed",
                    "provider": "resend",
                    "provider_message_id": None,
                    "error_message": f"Resend delivery failed: {exc}",
                    "external_recipient": recipient,
                }
        if provider == "smtp":
            if not self.settings.smtp_host or not self.settings.smtp_from_email:
                return {
                    "status": "failed",
                    "provider": "smtp",
                    "provider_message_id": None,
                    "error_message": "SMTP settings are incomplete.",
                    "external_recipient": recipient,
                }
            message = EmailMessage()
            message["Subject"] = title
            message["From"] = self.settings.smtp_from_email
            message["To"] = recipient
            message.set_content(content)
            if self.settings.resend_reply_to_email:
                message["Reply-To"] = self.settings.resend_reply_to_email
            try:
                with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as client:
                    if self.settings.smtp_use_tls:
                        client.starttls()
                    if self.settings.smtp_username and self.settings.smtp_password:
                        client.login(self.settings.smtp_username, self.settings.smtp_password)
                    client.send_message(message)
                return {
                    "status": "sent",
                    "provider": "smtp",
                    "provider_message_id": None,
                    "error_message": None,
                    "external_recipient": recipient,
                }
            except (OSError, smtplib.SMTPException) as exc:
                return {
                    "status": "failed",
                    "provider": "smtp",
                    "provider_message_id": None,
                    "error_message": f"SMTP delivery failed: {exc}",
                    "external_recipient": recipient,
                }
        return {
            "status": "failed",
            "provider": provider,
            "provider_message_id": None,
            "error_message": f"Unknown email provider: {provider}",
            "external_recipient": recipient,
        }

    def _dispatch_line(self, *, title: str, content: str, recipient: str | None) -> dict[str, Any]:
        if not self.settings.line_channel_access_token:
            return {
                "status": "failed",
                "provider": "line",
                "provider_message_id": None,
                "error_message": "LINE channel access token is missing.",
                "external_recipient": recipient,
            }
        if not recipient:
            return {
                "status": "failed",
                "provider": "line",
                "provider_message_id": None,
                "error_message": "Missing LINE userId / external recipient.",
                "external_recipient": None,
            }
        payload = {
            "to": recipient,
            "messages": [
                {
                    "type": "text",
                    "text": f"{title}\n\n{content}"[:5000],
                }
            ],
        }
        try:
            response = httpx.post(
                f"{self.settings.line_api_base_url}/v2/bot/message/push",
                headers={
                    "Authorization": f"Bearer {self.settings.line_channel_access_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "JapanLifeLanguageSchoolOS/1.0",
                    "X-Line-Retry-Key": str(uuid4()),
                },
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            return {
                "status": "sent",
                "provider": "line",
                "provider_message_id": response.headers.get("x-line-request-id"),
                "error_message": None,
                "external_recipient": recipient,
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "status": "failed",
                "provider": "line",
                "provider_message_id": None,
                "error_message": f"LINE delivery failed: {exc}",
                "external_recipient": recipient,
            }

    @staticmethod
    def _render_email_html(title: str, content: str) -> str:
        escaped_title = escape(title)
        escaped_lines = "<br />".join(escape(line) for line in content.splitlines()) or "&nbsp;"
        return (
            "<div style='font-family:Arial,sans-serif;line-height:1.6;color:#1b2320'>"
            f"<h2 style='margin:0 0 12px'>{escaped_title}</h2>"
            f"<p style='margin:0'>{escaped_lines}</p>"
            "</div>"
        )
