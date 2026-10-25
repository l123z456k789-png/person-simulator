"""In-memory simulation sessions with explicit limits and tombstones."""

from __future__ import annotations

import secrets
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import Field

from person_simulator.errors import (
    InputError,
    InputTooLongError,
    SessionEndedError,
    SessionExpiredError,
    SessionLimitError,
    SessionNotFoundError,
    SessionRateLimitError,
    TurnLimitError,
)
from person_simulator.models import StrictModel
from person_simulator.storage import utcnow


class SessionState(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    EXPIRED = "expired"
    DELETED = "deleted"


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    created_at: datetime


@dataclass
class Session:
    id: str
    invite_id: str
    created_at: datetime
    last_active: datetime
    state: SessionState = SessionState.ACTIVE
    turns: int = 0
    messages: list[ChatMessage] = field(default_factory=list)
    ended_at: datetime | None = None
    request_times: deque[datetime] = field(default_factory=deque)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class SessionManager:
    def __init__(
        self,
        *,
        max_sessions: int,
        ttl: timedelta,
        idle: timedelta,
        max_turns: int,
        max_input_chars: int,
        requests_per_minute: int,
        tombstone_seconds: int = 300,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.max_sessions = max_sessions
        self.ttl = ttl
        self.idle = idle
        self.max_turns = max_turns
        self.max_input_chars = max_input_chars
        self.requests_per_minute = requests_per_minute
        self.tombstone_seconds = tombstone_seconds
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def _now(self) -> datetime:
        return self._clock()

    def _count_active_unlocked(self, invite_id: str | None = None) -> int:
        return sum(
            1
            for session in self._sessions.values()
            if session.state == SessionState.ACTIVE
            and (invite_id is None or session.invite_id == invite_id)
        )

    def count_active(self, invite_id: str) -> int:
        with self._lock:
            return self._count_active_unlocked(invite_id)

    def _refresh_unlocked(self, session: Session, now: datetime) -> None:
        if session.state != SessionState.ACTIVE:
            return
        if now - session.created_at >= self.ttl:
            session.state = SessionState.EXPIRED
            session.ended_at = now
            session.messages.clear()
            session.request_times.clear()
            return
        if now - session.last_active >= self.idle:
            session.state = SessionState.EXPIRED
            session.ended_at = now
            session.messages.clear()
            session.request_times.clear()

    def sweep(self, now: datetime | None = None) -> None:
        current = now or self._now()
        with self._lock:
            expired_ids: list[str] = []
            for session_id, session in self._sessions.items():
                self._refresh_unlocked(session, current)
                if (
                    session.state in {SessionState.ENDED, SessionState.EXPIRED}
                    and session.ended_at is not None
                    and (current - session.ended_at).total_seconds()
                    >= self.tombstone_seconds
                ):
                    expired_ids.append(session_id)
            for session_id in expired_ids:
                self._sessions.pop(session_id, None)

    def create(
        self,
        invite_id: str,
        *,
        max_sessions_for_invite: int | None = None,
    ) -> Session:
        current = self._now()
        self.sweep(current)
        with self._lock:
            if self._count_active_unlocked() >= self.max_sessions:
                raise SessionLimitError(
                    "达到全局会话上限", stage="simulation"
                )
            if (
                max_sessions_for_invite is not None
                and self._count_active_unlocked(invite_id) >= max_sessions_for_invite
            ):
                raise SessionLimitError(
                    "达到该邀请的会话上限", stage="simulation"
                )
            session = Session(
                id=secrets.token_urlsafe(24),
                invite_id=invite_id,
                created_at=current,
                last_active=current,
            )
            self._sessions[session.id] = session
            return session

    def get(self, session_id: str) -> Session:
        current = self._now()
        self.sweep(current)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(
                    "会话不存在或已删除", stage="simulation"
                )
            if session.state == SessionState.ENDED:
                raise SessionEndedError("会话已结束", stage="simulation")
            if session.state == SessionState.EXPIRED:
                raise SessionExpiredError("会话已过期", stage="simulation")
            return session

    def end(self, session_id: str) -> None:
        current = self._now()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(
                    "会话不存在或已删除", stage="simulation"
                )
            if session.state == SessionState.ACTIVE:
                session.state = SessionState.ENDED
                session.ended_at = current
                session.messages.clear()
                session.request_times.clear()

    def delete(self, session_id: str) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(
                    "会话不存在或已删除", stage="simulation"
                )
            del self._sessions[session_id]

    def list_metadata(self) -> list[dict[str, object]]:
        self.sweep()
        with self._lock:
            return [
                {
                    "id": session.id,
                    "invite_id": session.invite_id,
                    "state": session.state.value,
                    "turns": session.turns,
                    "created_at": session.created_at.isoformat(),
                    "last_active": session.last_active.isoformat(),
                    "ended_at": (
                        session.ended_at.isoformat() if session.ended_at else None
                    ),
                }
                for session in sorted(
                    self._sessions.values(), key=lambda item: item.created_at
                )
            ]

    def check_input(self, session: Session, text: str) -> None:
        if not text.strip():
            raise InputError("输入不能为空", stage="simulation")
        if len(text) > self.max_input_chars:
            raise InputTooLongError(
                "输入超过长度上限",
                stage="simulation",
                hint=f"max_input_chars={self.max_input_chars}",
            )

    def check_turn(self, session: Session) -> None:
        if session.turns >= self.max_turns:
            raise TurnLimitError(
                "达到会话轮数上限",
                stage="simulation",
                hint=f"max_turns={self.max_turns}",
            )

    def note_request(self, session: Session, now: datetime | None = None) -> None:
        current = now or self._now()
        with session.lock:
            cutoff = current - timedelta(minutes=1)
            while session.request_times and session.request_times[0] < cutoff:
                session.request_times.popleft()
            if len(session.request_times) >= self.requests_per_minute:
                raise SessionRateLimitError(
                    "请求过于频繁", stage="simulation"
                )
            session.request_times.append(current)

    def record_exchange(
        self,
        session: Session,
        user_text: str,
        assistant_text: str,
        now: datetime | None = None,
    ) -> None:
        current = now or self._now()
        with session.lock:
            if session.state != SessionState.ACTIVE:
                raise SessionEndedError("会话已结束", stage="simulation")
            session.messages.append(
                ChatMessage(role="user", content=user_text, created_at=current)
            )
            session.messages.append(
                ChatMessage(
                    role="assistant", content=assistant_text, created_at=current
                )
            )
            session.turns += 1
            session.last_active = current
