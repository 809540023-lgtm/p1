from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import json
from typing import Any

import httpx

from school_platform.config import SchoolPlatformSettings, load_settings


def _minor_units(amount: float, currency: str) -> int:
    currency_code = currency.lower()
    if currency_code in {"jpy", "krw"}:
        return int(round(amount))
    return int(round(amount * 100))


@dataclass(slots=True)
class SchoolPlatformPaymentRuntime:
    settings: SchoolPlatformSettings | None = None

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = load_settings()

    def status(self) -> dict[str, Any]:
        provider = self.settings.payment_provider
        stripe_secret_present = bool(self.settings.stripe_secret_key)
        stripe_webhook_present = bool(self.settings.stripe_webhook_secret)
        success_url = self._success_url_template()
        cancel_url = self._cancel_url_template()
        ready = provider == "mock" or (
            provider == "stripe"
            and stripe_secret_present
            and stripe_webhook_present
            and bool(success_url)
            and bool(cancel_url)
        )
        return {
            "provider": provider,
            "ready": ready,
            "currency": self.settings.payment_currency.upper(),
            "stripe_secret_key_present": stripe_secret_present,
            "stripe_publishable_key_present": bool(self.settings.stripe_publishable_key),
            "stripe_webhook_secret_present": stripe_webhook_present,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "app_base_url": self.settings.app_base_url,
            "mode": "external" if provider == "stripe" else "mock",
            "provider_mode": self._provider_mode(),
            "reconciliation_supported": provider == "stripe",
            "webhook_tolerance_seconds": self.settings.stripe_webhook_tolerance_seconds,
            "supported_methods": ["card", "transfer", "cash"],
            "message": self._status_message(provider, ready),
        }

    def _status_message(self, provider: str, ready: bool) -> str:
        if provider == "mock":
            return "使用內建 mock 金流。"
        if provider == "stripe" and ready:
            return "Stripe Checkout 已可用。"
        if provider == "stripe":
            return "Stripe 已指定，但尚未補齊 secret key / webhook secret / return URLs。"
        return f"未知金流 provider：{provider}"

    def _success_url_template(self) -> str:
        return (
            self.settings.stripe_success_url
            or f"{self.settings.app_base_url.rstrip('/')}/school-platform/payment"
            "?email={CHECKOUT_EMAIL}&order_no={CHECKOUT_ORDER_NO}&payment_result=success"
        )

    def _cancel_url_template(self) -> str:
        return (
            self.settings.stripe_cancel_url
            or f"{self.settings.app_base_url.rstrip('/')}/school-platform/payment"
            "?email={CHECKOUT_EMAIL}&order_no={CHECKOUT_ORDER_NO}&payment_result=cancel"
        )

    def _provider_mode(self) -> str:
        key = self.settings.stripe_secret_key or self.settings.stripe_publishable_key or ""
        if key.startswith(("sk_live_", "pk_live_")):
            return "live"
        if key.startswith(("sk_test_", "pk_test_")):
            return "test"
        if self.settings.payment_provider == "mock":
            return "mock"
        return "unknown"

    @staticmethod
    def _request_user_agent() -> str:
        return "JapanLifeLanguageSchoolOS/1.0"

    @staticmethod
    def _datetime_from_unix(value: Any) -> datetime | None:
        if value in {None, ""}:
            return None
        try:
            return datetime.fromtimestamp(int(value)).astimezone()
        except (TypeError, ValueError, OSError):
            return None

    def _stripe_headers(self, *, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.settings.stripe_secret_key or ''}",
            "User-Agent": self._request_user_agent(),
        }
        if extra:
            headers.update(extra)
        return headers

    def _raise_for_stripe_error(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        message = None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error_block = payload.get("error")
            if isinstance(error_block, dict):
                message = error_block.get("message") or error_block.get("code")
        if not message:
            message = response.text.strip() or f"HTTP {response.status_code}"
        raise RuntimeError(f"Stripe API error ({response.status_code}): {message}")

    def _require_stripe_ready(self) -> None:
        status = self.status()
        if status["provider"] != "stripe":
            raise RuntimeError("Payment provider is not set to stripe.")
        if not status["ready"]:
            raise RuntimeError(status["message"])

    def create_checkout_session(
        self,
        *,
        order_no: str,
        amount: float,
        payment_method: str,
        student_email: str,
        product_name: str,
        enrollment_id: str,
    ) -> dict[str, Any]:
        provider = self.settings.payment_provider
        if provider == "mock" or payment_method != "card":
            return {
                "provider": "mock",
                "provider_payment_id": None,
                "checkout_url": None,
                "client_token": f"demo_{order_no}",
                "provider_status": "pending",
                "currency": self.settings.payment_currency.upper(),
            }

        self._require_stripe_ready()
        success_url = self._success_url_template().replace("{CHECKOUT_EMAIL}", student_email).replace("{CHECKOUT_ORDER_NO}", order_no)
        cancel_url = self._cancel_url_template().replace("{CHECKOUT_EMAIL}", student_email).replace("{CHECKOUT_ORDER_NO}", order_no)
        payload = [
            ("mode", "payment"),
            ("success_url", success_url),
            ("cancel_url", cancel_url),
            ("customer_email", student_email),
            ("client_reference_id", order_no),
            ("metadata[order_no]", order_no),
            ("metadata[student_email]", student_email),
            ("metadata[enrollment_id]", enrollment_id),
            ("line_items[0][price_data][currency]", self.settings.payment_currency),
            ("line_items[0][price_data][unit_amount]", str(_minor_units(amount, self.settings.payment_currency))),
            ("line_items[0][price_data][product_data][name]", product_name[:120]),
            ("line_items[0][quantity]", "1"),
            ("payment_method_types[0]", "card"),
        ]
        idempotency_source = f"{order_no}:{payment_method}:{student_email}:{enrollment_id}"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    "https://api.stripe.com/v1/checkout/sessions",
                    data=payload,
                    headers=self._stripe_headers(
                        extra={"Idempotency-Key": hashlib.sha256(idempotency_source.encode("utf-8")).hexdigest()}
                    ),
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Stripe request failed: {exc}") from exc
        self._raise_for_stripe_error(response)
        data = response.json()
        return {
            "provider": "stripe",
            "provider_payment_id": data.get("id"),
            "checkout_url": data.get("url"),
            "client_token": data.get("id") or "",
            "provider_status": data.get("status") or "open",
            "currency": str(data.get("currency") or self.settings.payment_currency).upper(),
            "checkout_expires_at": self._datetime_from_unix(data.get("expires_at")),
            "raw": data,
        }

    def verify_and_parse_stripe_event(self, payload: bytes, signature_header: str | None) -> dict[str, Any]:
        self._require_stripe_ready()
        if not signature_header:
            raise RuntimeError("Stripe-Signature header is missing.")
        timestamp = None
        signatures: list[str] = []
        for part in signature_header.split(","):
            key, _, value = part.partition("=")
            if key == "t":
                timestamp = value
            elif key == "v1":
                signatures.append(value)
        if not timestamp or not signatures:
            raise RuntimeError("Stripe-Signature header is invalid.")
        try:
            webhook_timestamp = int(timestamp)
        except ValueError as exc:
            raise RuntimeError("Stripe-Signature timestamp is invalid.") from exc
        tolerance = max(int(self.settings.stripe_webhook_tolerance_seconds), 0)
        if tolerance and abs(datetime.now().timestamp() - webhook_timestamp) > tolerance:
            raise RuntimeError("Stripe webhook timestamp is outside the allowed tolerance.")
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
        expected = hmac.new(
            (self.settings.stripe_webhook_secret or "").encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if not any(hmac.compare_digest(expected, signature) for signature in signatures):
            raise RuntimeError("Stripe webhook signature verification failed.")
        return json.loads(payload.decode("utf-8"))

    def normalize_webhook_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = str(event.get("type") or "")
        data = event.get("data", {})
        obj = data.get("object", {}) if isinstance(data, dict) else {}
        metadata = obj.get("metadata", {}) if isinstance(obj, dict) else {}
        order_no = metadata.get("order_no") or obj.get("client_reference_id")
        if not order_no:
            return None
        if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded", "payment_intent.succeeded"}:
            status = "paid"
        elif event_type in {"checkout.session.expired", "checkout.session.async_payment_failed", "payment_intent.payment_failed"}:
            status = "failed"
        elif event_type in {"charge.refunded", "charge.refund.updated"}:
            status = "refunded"
        else:
            return None
        paid_at = datetime.now().astimezone().isoformat() if status == "paid" else None
        return {
            "order_no": order_no,
            "status": status,
            "provider": "stripe",
            "provider_payment_id": obj.get("id"),
            "provider_status": obj.get("payment_status") or obj.get("status") or event_type,
            "event_type": event_type,
            "paid_at": paid_at,
        }

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        self._require_stripe_ready()
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(
                    f"https://api.stripe.com/v1/checkout/sessions/{session_id}",
                    headers=self._stripe_headers(),
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Stripe reconcile request failed: {exc}") from exc
        self._raise_for_stripe_error(response)
        return response.json()

    def normalize_checkout_session_for_reconcile(self, session: dict[str, Any]) -> dict[str, Any] | None:
        metadata = session.get("metadata", {}) if isinstance(session, dict) else {}
        order_no = metadata.get("order_no") or session.get("client_reference_id")
        if not order_no:
            return None
        stripe_status = str(session.get("status") or "")
        payment_status = str(session.get("payment_status") or "")
        normalized_status = None
        if payment_status == "paid":
            normalized_status = "paid"
        elif stripe_status == "expired":
            normalized_status = "failed"
        return {
            "order_no": order_no,
            "status": normalized_status,
            "provider": "stripe",
            "provider_payment_id": session.get("id"),
            "provider_status": payment_status or stripe_status or "open",
            "checkout_expires_at": self._datetime_from_unix(session.get("expires_at")),
        }
