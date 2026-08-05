from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from manim_workbench_api.content_plans.errors import ContentPlanError, ContentPlanErrorCode
from manim_workbench_api.content_plans.models import ProviderMessage, ProviderResult, ProviderUsage

_BASE_URL = "https://api.deepseek.com"
_MODEL = "deepseek-v4-flash"
_TIMEOUT = httpx.Timeout(connect=5.0, read=45.0, write=15.0, pool=5.0)


@dataclass(frozen=True)
class DeepSeekSettings:
    """Fixed DeepSeek configuration with the credential supplied by the environment."""

    api_key: str = field(repr=False)
    base_url: str = field(default=_BASE_URL, init=False)
    model: str = field(default=_MODEL, init=False)
    timeout: httpx.Timeout = field(default=_TIMEOUT, init=False, repr=False)

    @classmethod
    def from_environment(cls) -> DeepSeekSettings:
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise ContentPlanError(
                ContentPlanErrorCode.CONFIGURATION_ERROR,
                "DeepSeek provider is not configured.",
            )
        return cls(api_key=api_key)


class DeepSeekProvider:
    """One-shot, non-retrying DeepSeek Chat Completion boundary."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = DeepSeekSettings.from_environment()
        self._client = httpx.Client(
            base_url=self._settings.base_url,
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self._settings.timeout,
            transport=transport,
        )

    def generate(self, messages: tuple[ProviderMessage, ...]) -> ProviderResult:
        try:
            response = self._client.post(
                "/chat/completions",
                json={
                    "model": self._settings.model,
                    "messages": [message.model_dump() for message in messages],
                    "thinking": {"type": "disabled"},
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "max_tokens": 12000,
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_UNAVAILABLE,
                "DeepSeek provider is unavailable.",
            ) from error

        self._raise_for_status(response.status_code)
        payload = self._read_payload(response)
        return self._to_result(payload, response.headers.get("x-request-id"))

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if status_code in {400, 422}:
            code = ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR
        elif status_code in {401, 402}:
            code = ContentPlanErrorCode.PROVIDER_AUTH_ERROR
        elif status_code == 429:
            code = ContentPlanErrorCode.PROVIDER_RATE_LIMITED
        elif status_code in {500, 503}:
            code = ContentPlanErrorCode.PROVIDER_UNAVAILABLE
        elif 200 <= status_code < 300:
            return
        else:
            code = ContentPlanErrorCode.PROVIDER_UNAVAILABLE
        raise ContentPlanError(code, "DeepSeek provider request failed.")

    @staticmethod
    def _read_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR,
                "DeepSeek provider returned an invalid response envelope.",
            ) from error
        if not isinstance(payload, dict):
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR,
                "DeepSeek provider returned an invalid response envelope.",
            )
        return payload

    def _to_result(self, payload: dict[str, Any], request_id: str | None) -> ProviderResult:
        try:
            choices = payload["choices"]
            choice = choices[0]
            message = choice["message"]
            content = message["content"]
            finish_reason = choice.get("finish_reason")
        except (IndexError, KeyError, TypeError, AttributeError) as error:
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR,
                "DeepSeek provider returned an invalid response envelope.",
            ) from error

        if finish_reason == "length":
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_TRUNCATED_RESPONSE,
                "DeepSeek provider response was truncated.",
            )
        if not isinstance(content, str):
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR,
                "DeepSeek provider returned an invalid response envelope.",
            )
        if not content.strip():
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_EMPTY_RESPONSE,
                "DeepSeek provider returned an empty response.",
            )

        usage_payload = payload.get("usage", {})
        if not isinstance(usage_payload, dict):
            usage_payload = {}
        usage = ProviderUsage(
            prompt_tokens=self._usage_value(usage_payload, "prompt_tokens"),
            completion_tokens=self._usage_value(usage_payload, "completion_tokens"),
        )
        model = payload.get("model", self._settings.model)
        if not isinstance(model, str) or not model:
            model = self._settings.model
        return ProviderResult(
            content=content,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            request_id=request_id,
            model=model,
            usage=usage,
        )

    @staticmethod
    def _usage_value(usage_payload: dict[str, Any], field_name: str) -> int:
        value = usage_payload.get(field_name, 0)
        return value if isinstance(value, int) and value >= 0 else 0
