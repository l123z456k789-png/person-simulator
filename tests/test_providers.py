from __future__ import annotations

import json

import httpx
import pytest

from person_simulator.config import load_settings
from person_simulator.errors import (
    AuthenticationError,
    ContextLimitError,
    OutputTruncatedError,
    RateLimitError,
    ResponseFormatError,
    TransportError,
)
from person_simulator.providers.base import ModelRequest
from person_simulator.providers.mock import MockClient
from person_simulator.providers.openai_chat import OpenAIChatClient
from person_simulator.providers.retry import complete_with_retry


def _api_settings(tmp_path, **overrides):
    config = tmp_path / "config.toml"
    config.write_text(
        """
[model]
mode = "api"
provider = "openai_chat"
model = "test-model"
base_url = "https://api.example.com/v1"
context_window = 32768
""",
        encoding="utf-8",
    )
    return load_settings(
        config_path=config,
        env={"PSIM_API_KEY": "sk-secret"},
        cli_overrides=overrides,
    )


def _request(task_id="extract:c1"):
    return ModelRequest(
        task_id=task_id,
        messages=[{"role": "user", "content": "hello"}],
        output_limit=123,
    )


def _ok_payload(content='{"ok": true}'):
    return {
        "id": "req-1",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    }


def test_url_bearer_and_minimal_body(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_payload())

    settings = _api_settings(tmp_path)
    client = OpenAIChatClient(settings, transport=httpx.MockTransport(handler))
    response = client.complete(_request())
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-secret"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["max_tokens"] == 123
    assert "temperature" not in captured["body"]
    assert "response_format" not in captured["body"]
    assert "tools" not in captured["body"]
    assert "stream" not in captured["body"]
    assert response.content == '{"ok": true}'
    assert response.finish_reason == "stop"
    client.close()


def test_optional_parameters_only_when_enabled(tmp_path):
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_payload())

    settings = _api_settings(
        tmp_path,
        json_object=True,
        temperature=0.4,
        output_limit_param="max_completion_tokens",
        disable_thinking=True,
    )
    client = OpenAIChatClient(settings, transport=httpx.MockTransport(handler))
    client.complete(_request())
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["temperature"] == 0.4
    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert captured["body"]["max_completion_tokens"] == 123
    assert "max_tokens" not in captured["body"]


def test_auth_error_does_not_leak_key(tmp_path):
    settings = _api_settings(tmp_path)
    client = OpenAIChatClient(
        settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "no"})),
    )
    with pytest.raises(AuthenticationError) as error:
        client.complete(_request())
    assert "sk-secret" not in str(error.value)


def test_rate_limit_retry_after(tmp_path):
    settings = _api_settings(tmp_path)
    client = OpenAIChatClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "7"})
        ),
    )
    with pytest.raises(RateLimitError) as error:
        client.complete(_request())
    assert error.value.retry_after == 7


def test_context_length_400_classified(tmp_path):
    settings = _api_settings(tmp_path)
    client = OpenAIChatClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, text="maximum context length exceeded")
        ),
    )
    with pytest.raises(ContextLimitError):
        client.complete(_request())


def test_finish_reason_length_and_unknown(tmp_path):
    settings = _api_settings(tmp_path)
    for finish in ("length", "content_filter"):
        payload = _ok_payload()
        payload["choices"][0]["finish_reason"] = finish
        client = OpenAIChatClient(
            settings,
            transport=httpx.MockTransport(lambda request, p=payload: httpx.Response(200, json=p)),
        )
        expected = OutputTruncatedError if finish == "length" else ResponseFormatError
        with pytest.raises(expected):
            client.complete(_request())


def test_malformed_200_rejected(tmp_path):
    settings = _api_settings(tmp_path)
    for payload in (
        {},
        {"choices": []},
        {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
        {"choices": [{"message": {}, "finish_reason": "stop"}]},
    ):
        client = OpenAIChatClient(
            settings,
            transport=httpx.MockTransport(lambda request, p=payload: httpx.Response(200, json=p)),
        )
        with pytest.raises(ResponseFormatError):
            client.complete(_request())


def test_transport_timeout_classified(tmp_path):
    settings = _api_settings(tmp_path)

    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    client = OpenAIChatClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError):
        client.complete(_request())


class FlakyClient:
    provider = "fake"
    is_mock = False

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        if self.calls <= self.failures:
            raise TransportError("boom", stage="provider")
        from person_simulator.providers.base import ModelResponse

        return ModelResponse(content="ok", finish_reason="stop")


def test_retry_stops_after_max_attempts():
    client = FlakyClient(99)
    sleeps = []
    with pytest.raises(TransportError):
        complete_with_retry(client, _request(), max_attempts=3, sleep=sleeps.append)
    assert client.calls == 3
    assert len(sleeps) == 2
    assert all(0 <= delay <= 30 for delay in sleeps)


def test_retry_succeeds_and_counts_attempts():
    client = FlakyClient(1)
    sleeps = []
    response, attempts = complete_with_retry(
        client, _request(), max_attempts=3, sleep=sleeps.append
    )
    assert response.content == "ok"
    assert attempts == 2
    assert len(sleeps) == 1


def test_non_retryable_not_retried():
    class AuthClient:
        provider = "fake"
        is_mock = False

        def __init__(self):
            self.calls = 0

        def complete(self, request):
            self.calls += 1
            raise AuthenticationError("no", stage="provider")

    client = AuthClient()
    with pytest.raises(AuthenticationError):
        complete_with_retry(client, _request(), sleep=lambda delay: None)
    assert client.calls == 1


def test_mock_deterministic_and_offline():
    payload = {
        "task": "extract",
        "chunk_id": "c1",
        "target": "A",
        "interlocutor": "B",
        "core_parts": [
            {
                "part_id": "m1:p1",
                "message_id": "m1",
                "speaker": "A",
                "start": 0,
                "end": 2,
                "text": "你好",
            },
            {
                "part_id": "m2:p1",
                "message_id": "m2",
                "speaker": "B",
                "start": 0,
                "end": 2,
                "text": "你好",
            },
        ],
    }
    request = ModelRequest(
        task_id="extract:c1",
        messages=[
            {"role": "system", "content": "s"},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        output_limit=100,
    )
    first = MockClient().complete(request)
    second = MockClient().complete(request)
    assert first.content == second.content
    assert first.is_mock
    assert json.loads(first.content)["target"] == "A"


def test_mock_fault_injection():
    request = _request("extract:bad")
    with pytest.raises(TransportError):
        MockClient({"extract:bad": "timeout"}).complete(request)
    with pytest.raises(RateLimitError):
        MockClient({"extract:bad": "429"}).complete(request)
    with pytest.raises(OutputTruncatedError):
        MockClient({"extract:bad": "truncated"}).complete(request)
