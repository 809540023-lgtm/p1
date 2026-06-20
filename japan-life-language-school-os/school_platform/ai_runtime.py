from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, TypeVar

from pydantic import BaseModel

from config import settings as app_settings
from school_platform.schemas import AiProviderStatusResponse

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - import guard
    OpenAI = None


ModelT = TypeVar("ModelT", bound=BaseModel)


class SchoolPlatformAiRuntime:
    def __init__(self) -> None:
        self.requested_provider = (os.getenv("SCHOOL_PLATFORM_AI_PROVIDER") or "auto").strip().lower() or "auto"
        self._last_error: str | None = None
        self._client = None
        self._external_disabled = False

    def _sdk_available(self) -> bool:
        return OpenAI is not None

    def _external_requested(self) -> bool:
        return self.requested_provider in {"auto", "openai"}

    def _external_model_ready(self) -> bool:
        return (
            not self._external_disabled
            and self._external_requested()
            and self._sdk_available()
            and bool(app_settings.openai_api_key and app_settings.openai_model)
        )

    def _fallback_reason(self) -> str:
        if self.requested_provider == "fallback":
            return "provider_forced_to_fallback"
        if not app_settings.openai_api_key:
            return "missing_openai_api_key"
        if not self._sdk_available():
            return "openai_sdk_unavailable"
        if not app_settings.openai_model:
            return "missing_openai_model"
        return "fallback_local_mode"

    def status(self) -> AiProviderStatusResponse:
        external_model_ready = self._external_model_ready()
        return AiProviderStatusResponse(
            requested_provider=self.requested_provider,
            active_provider="openai" if external_model_ready else "fallback",
            runtime_mode="external_with_fallback" if external_model_ready else "local_fallback",
            service_ready=True,
            external_model_ready=external_model_ready,
            model_name=app_settings.openai_model,
            api_key_present=bool(app_settings.openai_api_key),
            sdk_available=self._sdk_available(),
            last_error=self._last_error,
            supported_features=[
                "招生跟進草稿",
                "AI 教案草稿",
                "學員 AI 情境對話",
                "週營運摘要",
            ],
        )

    def _get_client(self):
        if not self._external_model_ready():
            return None
        if self._client is None:
            self._client = OpenAI(api_key=app_settings.openai_api_key, timeout=4.0)
        return self._client

    @staticmethod
    def _strip_json_block(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        return cleaned.strip()

    @staticmethod
    def _merge_payload(base_payload: dict[str, Any], candidate_payload: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base_payload)
        for key, value in candidate_payload.items():
            if key not in merged:
                continue
            if value in (None, "", [], {}):
                continue
            merged[key] = value
        return merged

    def _generate_payload(
        self,
        *,
        feature_name: str,
        instructions: str,
        context: dict[str, Any],
        fallback_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str, str]:
        if not self._external_model_ready():
            return deepcopy(fallback_payload), "fallback", self._fallback_reason()

        client = self._get_client()
        if client is None:
            return deepcopy(fallback_payload), "fallback", self._fallback_reason()

        system_prompt = (
            "You are the AI operations assistant for a Japanese language school platform. "
            "Return strict JSON only. Preserve the same top-level keys as the fallback payload. "
            "Use Traditional Chinese for user-facing copy unless the payload already contains a different language. "
            "Do not wrap the JSON in markdown."
        )
        user_prompt = (
            f"Feature: {feature_name}\n"
            f"Instructions: {instructions}\n"
            f"Context JSON:\n{json.dumps(context, ensure_ascii=False)}\n"
            f"Fallback JSON:\n{json.dumps(fallback_payload, ensure_ascii=False)}\n"
            "Return an improved JSON payload with the same top-level keys."
        )

        try:
            response = client.responses.create(
                model=app_settings.openai_model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw_text = response.output_text if hasattr(response, "output_text") else ""
            parsed = json.loads(self._strip_json_block(raw_text))
            if not isinstance(parsed, dict):
                raise ValueError("AI response was not a JSON object")
            self._last_error = None
            return self._merge_payload(fallback_payload, parsed), "openai", "model_generated"
        except Exception as exc:  # pragma: no cover - exercised only when external provider is configured
            self._last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            self._external_disabled = True
            return deepcopy(fallback_payload), "fallback", f"external_error:{type(exc).__name__}"

    def enhance_model(
        self,
        *,
        feature_name: str,
        instructions: str,
        context: dict[str, Any],
        fallback_model: ModelT,
    ) -> tuple[ModelT, str, str]:
        payload, provider, reason = self._generate_payload(
            feature_name=feature_name,
            instructions=instructions,
            context=context,
            fallback_payload=fallback_model.model_dump(mode="json"),
        )
        return fallback_model.__class__.model_validate(payload), provider, reason

    def enhance_mapping(
        self,
        *,
        feature_name: str,
        instructions: str,
        context: dict[str, Any],
        fallback_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str, str]:
        return self._generate_payload(
            feature_name=feature_name,
            instructions=instructions,
            context=context,
            fallback_payload=fallback_payload,
        )
