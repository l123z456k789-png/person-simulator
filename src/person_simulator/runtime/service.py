"""Chat service for a loaded runtime persona."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from person_simulator.budget import PACKAGING_MARGIN, estimate_tokens, safety_margin
from person_simulator.config import Settings
from person_simulator.errors import ContextLimitError, OutputBlockedError
from person_simulator.providers.base import ModelClient, ModelRequest
from person_simulator.providers.runner import RequestRunner
from person_simulator.runtime.guard import OutputGuard
from person_simulator.runtime.models import RuntimePersona
from person_simulator.runtime.session import ChatMessage, SessionManager
from person_simulator.storage import utcnow


@dataclass(frozen=True)
class ChatReply:
    text: str
    redactions: int
    turn: int
    notices: tuple[str, ...] = ()


def _history_tokens(history: list[ChatMessage]) -> int:
    return sum(estimate_tokens(message.content) for message in history)


def build_model_messages(
    system_prompt: str,
    history: list[ChatMessage],
    user_message: str,
    *,
    context_window: int,
    output_limit: int,
) -> list[dict[str, str]]:
    """Build a bounded prompt, dropping oldest turns before failing."""

    base = (
        PACKAGING_MARGIN
        + estimate_tokens(system_prompt)
        + estimate_tokens(user_message)
        + output_limit
        + safety_margin(context_window)
    )
    if base > context_window:
        raise ContextLimitError(
            "上下文预算不足以容纳 system prompt 与当前输入",
            stage="simulation",
            hint=f"context_window={context_window}, output_limit={output_limit}",
        )

    remaining = list(history)
    while remaining and base + _history_tokens(remaining) > context_window:
        remaining = remaining[2:] if len(remaining) >= 2 else []

    return (
        [{"role": "system", "content": system_prompt}]
        + [{"role": message.role, "content": message.content} for message in remaining]
        + [{"role": "user", "content": user_message}]
    )


class ChatService:
    def __init__(
        self,
        *,
        persona: RuntimePersona,
        settings: Settings,
        client: ModelClient,
        manager: SessionManager,
        guard: OutputGuard,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.persona = persona
        self.settings = settings
        self.client = client
        self.manager = manager
        self.guard = guard
        self._clock = clock

    def chat(self, session_id: str, message: str) -> ChatReply:
        session = self.manager.get(session_id)
        self.manager.check_input(session, message)
        self.manager.check_turn(session)
        self.manager.note_request(session)

        output_limit = min(
            self.settings.simulation.max_output_tokens,
            self.settings.model.max_output_tokens,
        )
        messages = build_model_messages(
            self.persona.system_prompt,
            session.messages,
            message,
            context_window=self.settings.effective_context_window,
            output_limit=output_limit,
        )
        runner = RequestRunner(
            self.client,
            max_attempts=self.settings.retry.max_attempts,
            max_requests=self.settings.retry.max_attempts,
        )
        response = runner.call(
            ModelRequest(
                task_id=f"simulate:{session.id}:{session.turns + 1}",
                messages=messages,
                output_limit=output_limit,
            )
        )
        checked = self.guard.check(response.content)
        if checked.blocked:
            raise OutputBlockedError(
                "模拟回复未通过安全检查",
                stage="simulation",
                hint=checked.reason,
            )

        self.manager.record_exchange(
            session,
            message,
            checked.text,
            now=self._clock(),
        )
        notices: list[str] = []
        if self.persona.is_mock or self.settings.is_mock:
            notices.append("MOCK 合成演示，不代表真实人物")
        if checked.redactions:
            notices.append(f"已隐藏 {checked.redactions} 处直接身份信息")
        return ChatReply(
            text=checked.text,
            redactions=checked.redactions,
            turn=session.turns,
            notices=tuple(notices),
        )

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
