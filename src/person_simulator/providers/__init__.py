"""Provider factory."""

from __future__ import annotations

import httpx

from person_simulator.config import Settings
from person_simulator.errors import ConfigError
from person_simulator.providers.base import ModelClient
from person_simulator.providers.mock import MockClient
from person_simulator.providers.openai_chat import OpenAIChatClient


def build_client(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
) -> ModelClient:
    if settings.model.mode == "mock":
        return MockClient()
    if settings.model.mode == "api":
        if settings.model.provider != "openai_chat":
            raise ConfigError(
                "api 模式当前仅支持 provider=openai_chat",
                stage="provider",
            )
        return OpenAIChatClient(settings, transport=transport)
    raise ConfigError("未知运行模式", stage="provider")
