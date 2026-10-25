"""Provider-neutral request/response protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelRequest:
    task_id: str
    messages: list[dict[str, str]]
    output_limit: int
    schema: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    content: str
    finish_reason: str | None
    usage: dict[str, int] | None = None
    request_id: str | None = None
    provider: str = "unknown"
    is_mock: bool = False


class ModelClient(Protocol):
    provider: str
    is_mock: bool

    def complete(self, request: ModelRequest) -> ModelResponse: ...
