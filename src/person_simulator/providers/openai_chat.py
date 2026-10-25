"""Minimal OpenAI-compatible chat-completions adapter (non-streaming)."""

from __future__ import annotations

import httpx

from person_simulator.config import Settings
from person_simulator.errors import (
    APIError,
    AuthenticationError,
    ContextLimitError,
    OutputTruncatedError,
    ProviderUnavailable,
    RateLimitError,
    ResponseFormatError,
    TransportError,
)
from person_simulator.providers.base import ModelRequest, ModelResponse


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class OpenAIChatClient:
    provider = "openai_chat"
    is_mock = False

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not settings.api_key:
            raise AuthenticationError(
                "缺少 PSIM_API_KEY",
                stage="provider",
                hint="仅在需要真实 API 时设置环境变量 PSIM_API_KEY",
            )
        if not settings.model.base_url:  # pragma: no cover - validated by config
            raise APIError("缺少 base_url", stage="provider")
        self._api_key = settings.api_key
        self._url = settings.model.base_url.rstrip("/") + "/chat/completions"
        self._model = settings.model.model
        self._output_param = settings.model.output_limit_param
        self._json_object = settings.model.json_object
        self._disable_thinking = settings.model.disable_thinking
        self._temperature = settings.model.temperature
        timeout = httpx.Timeout(
            connect=settings.retry.connect_timeout,
            read=settings.retry.read_timeout,
            write=settings.retry.read_timeout,
            pool=settings.retry.connect_timeout,
        )
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=settings.security.trust_env,
            transport=transport,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def complete(self, request: ModelRequest) -> ModelResponse:
        body: dict[str, object] = {
            "model": self._model,
            "messages": request.messages,
            self._output_param: request.output_limit,
        }
        if self._temperature is not None:
            body["temperature"] = self._temperature
        if self._json_object:
            body["response_format"] = {"type": "json_object"}
        if self._disable_thinking:
            body["thinking"] = {"type": "disabled"}

        try:
            response = self._client.post(
                self._url,
                json=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise TransportError(
                "请求超时",
                stage="provider",
                task_id=request.task_id,
                hint="检查网络或提高 retry.read_timeout；重试可能重复计费",
            ) from exc
        except httpx.HTTPError as exc:
            raise TransportError(
                "网络传输失败",
                stage="provider",
                task_id=request.task_id,
                hint="检查 base_url、网络与 TLS 证书",
            ) from exc

        if response.status_code in (401, 403):
            raise AuthenticationError(
                "服务商拒绝鉴权",
                stage="provider",
                task_id=request.task_id,
                hint="确认 PSIM_API_KEY 有效且未过期",
            )
        if response.status_code == 429:
            error = RateLimitError(
                "服务商限流",
                stage="provider",
                task_id=request.task_id,
                hint="等待 Retry-After 或降低请求频率",
            )
            error.retry_after = _retry_after(response)  # type: ignore[attr-defined]
            raise error
        if response.status_code in (500, 502, 503, 504):
            error = ProviderUnavailable(
                f"服务商暂时不可用（HTTP {response.status_code}）",
                stage="provider",
                task_id=request.task_id,
                hint="稍后有界重试；持续失败时检查服务商状态",
            )
            error.retry_after = _retry_after(response)  # type: ignore[attr-defined]
            raise error
        if response.status_code == 400:
            detail = response.text.lower()
            if "context" in detail and ("length" in detail or "token" in detail):
                raise ContextLimitError(
                    "请求超出模型上下文长度",
                    stage="provider",
                    task_id=request.task_id,
                    hint="上层会缩小输入并重新切分，不重复同一超限请求",
                )
            raise APIError(
                "服务商拒绝请求（HTTP 400）",
                stage="provider",
                task_id=request.task_id,
                hint="检查 model、参数能力与请求格式",
            )
        if response.status_code != 200:
            raise APIError(
                f"服务商返回非预期状态（HTTP {response.status_code}）",
                stage="provider",
                task_id=request.task_id,
                hint="检查 API 根地址与账户状态；不跟随重定向",
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ResponseFormatError(
                "响应不是 JSON",
                stage="provider",
                task_id=request.task_id,
                hint="确认 base_url 指向 API 而不是网页聊天地址",
            ) from exc

        if not isinstance(data, dict):
            raise ResponseFormatError(
                "响应 JSON 顶层不是对象",
                stage="provider",
                task_id=request.task_id,
            )
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ResponseFormatError(
                "响应缺少 choices[0]",
                stage="provider",
                task_id=request.task_id,
            )
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ResponseFormatError(
                "响应缺少 message 对象",
                stage="provider",
                task_id=request.task_id,
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ResponseFormatError(
                "响应 content 为空或不是文本",
                stage="provider",
                task_id=request.task_id,
                hint="过滤、工具调用或空内容都不视为成功",
            )
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise OutputTruncatedError(
                "模型输出被截断",
                stage="provider",
                task_id=request.task_id,
                hint="减小单个任务输入或提高输出上限",
            )
        if finish_reason != "stop":
            raise ResponseFormatError(
                "finish_reason 不是 stop",
                stage="provider",
                task_id=request.task_id,
                hint="不把未知结束原因当成成功",
            )

        usage = data.get("usage")
        clean_usage: dict[str, int] | None = None
        if isinstance(usage, dict):
            clean_usage = {
                str(key): value
                for key, value in usage.items()
                if isinstance(value, int) and not isinstance(value, bool)
            } or None
        request_id = data.get("id") if isinstance(data.get("id"), str) else response.headers.get("x-request-id")
        return ModelResponse(
            content=content,
            finish_reason=finish_reason,
            usage=clean_usage,
            request_id=request_id,
            provider=self.provider,
            is_mock=False,
        )
