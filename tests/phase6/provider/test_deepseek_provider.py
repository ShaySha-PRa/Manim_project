from __future__ import annotations

import json

import httpx
import pytest
from manim_workbench_api.content_plans.errors import ContentPlanError, ContentPlanErrorCode
from manim_workbench_api.content_plans.models import ProviderMessage
from manim_workbench_api.content_plans.provider import DeepSeekProvider, DeepSeekSettings


@pytest.fixture(autouse=True)
def provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-provider-token")


def completion_response(
    *, content: str = '{"outcome":"ready"}', finish_reason: str = "stop"
) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "model": "deepseek-v4-flash",
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 34},
    }


def messages() -> tuple[ProviderMessage, ...]:
    return (
        ProviderMessage(role="system", content="Return json only."),
        ProviderMessage(role="user", content="Produce the requested plan in json."),
    )


def test_settings_reject_missing_key_without_echoing_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY")

    with pytest.raises(ContentPlanError) as caught:
        DeepSeekSettings.from_environment()

    assert caught.value.code is ContentPlanErrorCode.CONFIGURATION_ERROR
    assert "DEEPSEEK_API_KEY" not in str(caught.value)


def test_settings_repr_redacts_the_provider_token() -> None:
    settings = DeepSeekSettings.from_environment()

    assert "test-only-provider-token" not in repr(settings)


def test_generate_uses_the_fixed_deepseek_json_output_contract() -> None:
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "request-test-123"},
            json=completion_response(),
        )

    provider = DeepSeekProvider(transport=httpx.MockTransport(handler))

    result = provider.generate(messages())

    assert len(received) == 1
    request = received[0]
    assert request.url == "https://api.deepseek.com/chat/completions"
    assert request.headers["authorization"] == "Bearer test-only-provider-token"
    payload = json.loads(request.content)
    assert payload == {
        "model": "deepseek-v4-flash",
        "messages": [message.model_dump() for message in messages()],
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 12000,
    }
    assert "test-only-provider-token" not in request.content.decode()
    assert result.content == '{"outcome":"ready"}'
    assert result.finish_reason == "stop"
    assert result.request_id == "request-test-123"
    assert result.model == "deepseek-v4-flash"
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 34


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (400, ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR),
        (422, ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR),
        (401, ContentPlanErrorCode.PROVIDER_AUTH_ERROR),
        (402, ContentPlanErrorCode.PROVIDER_AUTH_ERROR),
        (429, ContentPlanErrorCode.PROVIDER_RATE_LIMITED),
        (500, ContentPlanErrorCode.PROVIDER_UNAVAILABLE),
        (503, ContentPlanErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_generate_maps_required_http_errors_without_leaking_response_body(
    status_code: int, expected_code: ContentPlanErrorCode
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, text="sensitive upstream diagnostic")

    provider = DeepSeekProvider(transport=httpx.MockTransport(handler))

    with pytest.raises(ContentPlanError) as caught:
        provider.generate(messages())

    assert calls == 1
    assert caught.value.code is expected_code
    assert "sensitive upstream diagnostic" not in str(caught.value)
    assert "test-only-provider-token" not in repr(caught.value)


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (httpx.ConnectTimeout("synthetic timeout"), ContentPlanErrorCode.PROVIDER_UNAVAILABLE),
        (
            httpx.ConnectError("synthetic network failure"),
            ContentPlanErrorCode.PROVIDER_UNAVAILABLE,
        ),
    ],
)
def test_generate_maps_timeout_and_network_errors_once(
    exception: httpx.HTTPError, expected_code: ContentPlanErrorCode
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exception

    provider = DeepSeekProvider(transport=httpx.MockTransport(handler))

    with pytest.raises(ContentPlanError) as caught:
        provider.generate(messages())

    assert calls == 1
    assert caught.value.code is expected_code


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (completion_response(content="   "), ContentPlanErrorCode.PROVIDER_EMPTY_RESPONSE),
        (
            completion_response(content="partial", finish_reason="length"),
            ContentPlanErrorCode.PROVIDER_TRUNCATED_RESPONSE,
        ),
        ({"choices": []}, ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR),
    ],
)
def test_generate_classifies_response_failures(
    payload: dict[str, object], expected_code: ContentPlanErrorCode
) -> None:
    provider = DeepSeekProvider(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )

    with pytest.raises(ContentPlanError) as caught:
        provider.generate(messages())

    assert caught.value.code is expected_code
