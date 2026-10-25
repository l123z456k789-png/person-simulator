from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest

from person_simulator.config import load_settings
from person_simulator.errors import ContextLimitError, OutputBlockedError, TransportError
from person_simulator.providers.base import ModelRequest, ModelResponse
from person_simulator.providers.mock import MockClient
from person_simulator.runtime.guard import OutputGuard
from person_simulator.runtime.models import RuntimePersona
from person_simulator.runtime.service import (
    ChatService,
    build_model_messages,
)
from person_simulator.runtime.session import ChatMessage, SessionManager
from person_simulator.storage import utcnow


class StaticClient:
    provider = "static"
    is_mock = False

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            content=self.content,
            finish_reason="stop",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            request_id=f"static-{self.calls}",
            provider=self.provider,
            is_mock=False,
        )

    def close(self) -> None:
        pass


def make_persona(system_prompt: str = "运行时 system prompt") -> RuntimePersona:
    return RuntimePersona(
        run_id="run-test",
        strategy="evidence",
        package_version="0.1.0",
        prompt_version="1.0",
        source_hash="a" * 64,
        target="A",
        interlocutor="B",
        system_prompt=system_prompt,
        system_prompt_sha256=hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        original_system_prompt_sha256="b" * 64,
        is_mock=True,
        created_at=utcnow(),
    )


def make_manager(**overrides) -> SessionManager:
    values = {
        "max_sessions": 4,
        "ttl": timedelta(minutes=30),
        "idle": timedelta(minutes=10),
        "max_turns": 5,
        "max_input_chars": 200,
        "requests_per_minute": 10,
    }
    values.update(overrides)
    return SessionManager(**values)


def make_service(
    *,
    client=None,
    guard: OutputGuard | None = None,
    settings=None,
    manager: SessionManager | None = None,
) -> ChatService:
    persona = make_persona()
    settings = settings or load_settings(env={})
    manager = manager or make_manager()
    guard = guard or OutputGuard(persona.system_prompt)
    return ChatService(
        persona=persona,
        settings=settings,
        client=client or MockClient(),
        manager=manager,
        guard=guard,
    )


def test_mock_client_supports_runtime_simulation():
    client = MockClient()
    response = client.complete(
        ModelRequest(
            task_id="simulate:session:1",
            messages=[{"role": "user", "content": "在吗"}],
            output_limit=32,
        )
    )
    assert "MOCK" in response.content


def test_mock_chat_roundtrip_and_history():
    service = make_service()
    session = service.manager.create("invite-1")

    reply = service.chat(session.id, "在吗？")

    assert "MOCK" in reply.text
    assert reply.turn == 1
    assert len(session.messages) == 2
    assert session.messages[0].role == "user"
    assert session.messages[0].content == "在吗？"
    assert session.messages[1].role == "assistant"


def test_provider_failure_does_not_write_history():
    service = make_service(client=MockClient(faults={"*": "timeout"}))
    session = service.manager.create("invite-1")

    with pytest.raises(TransportError):
        service.chat(session.id, "在吗？")

    assert session.messages == []
    assert session.turns == 0


def test_output_blocked_does_not_write_history():
    service = make_service(
        client=StaticClient("张三"),
        guard=OutputGuard("prompt", blocked_terms=["张三"]),
    )
    session = service.manager.create("invite-1")

    with pytest.raises(OutputBlockedError):
        service.chat(session.id, "在吗？")

    assert session.messages == []
    assert session.turns == 0


def test_redacted_output_is_stored_redacted():
    service = make_service(client=StaticClient("电话 13800138000"))
    session = service.manager.create("invite-1")

    reply = service.chat(session.id, "你的电话？")

    assert reply.redactions >= 1
    assert "13800138000" not in reply.text
    assert "13800138000" not in session.messages[1].content
    assert "[已隐藏]" in session.messages[1].content


def test_two_sessions_do_not_share_history():
    service = make_service()
    first = service.manager.create("invite-1")
    second = service.manager.create("invite-2")

    service.chat(first.id, "第一个会话")
    assert first.messages
    assert second.messages == []

    service.chat(second.id, "第二个会话")
    assert second.messages[0].content == "第二个会话"


def test_build_model_messages_drops_oldest_turns():
    history = [
        ChatMessage(
            role="user" if index % 2 == 0 else "assistant",
            content="x" * 500,
            created_at=utcnow(),
        )
        for index in range(20)
    ]

    messages = build_model_messages(
        "system",
        history,
        "new",
        context_window=8000,
        output_limit=64,
    )

    assert messages[0] == {"role": "system", "content": "system"}
    assert messages[-1] == {"role": "user", "content": "new"}
    assert 2 < len(messages) < 22


def test_build_model_messages_rejects_oversized_system_prompt():
    with pytest.raises(ContextLimitError):
        build_model_messages(
            "x" * 10_000,
            [],
            "new",
            context_window=2000,
            output_limit=100,
        )
