from __future__ import annotations

from datetime import timedelta

import pytest

from person_simulator.errors import (
    InputTooLongError,
    SessionEndedError,
    SessionExpiredError,
    SessionLimitError,
    SessionNotFoundError,
    SessionRateLimitError,
    TurnLimitError,
)
from person_simulator.runtime.session import ChatMessage, SessionManager
from person_simulator.storage import utcnow


class Clock:
    def __init__(self) -> None:
        self.now = utcnow()

    def __call__(self):
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def make_manager(clock: Clock | None = None, **overrides) -> SessionManager:
    clock = clock or Clock()
    values = {
        "max_sessions": 2,
        "ttl": timedelta(minutes=30),
        "idle": timedelta(minutes=10),
        "max_turns": 3,
        "max_input_chars": 20,
        "requests_per_minute": 2,
        "tombstone_seconds": 300,
        "clock": clock,
    }
    values.update(overrides)
    return SessionManager(**values)


def test_create_and_isolation():
    manager = make_manager()
    first = manager.create("invite-a")
    second = manager.create("invite-b")

    assert first.id != second.id
    first.messages.append(
        ChatMessage(role="user", content="one", created_at=utcnow())
    )
    assert second.messages == []


def test_max_sessions_and_delete():
    manager = make_manager(max_sessions=1)
    first = manager.create("invite-a")

    with pytest.raises(SessionLimitError):
        manager.create("invite-a")

    manager.delete(first.id)
    with pytest.raises(SessionNotFoundError):
        manager.get(first.id)


def test_per_invite_session_limit():
    manager = make_manager(max_sessions=10)
    manager.create("invite-a", max_sessions_for_invite=1)

    with pytest.raises(SessionLimitError):
        manager.create("invite-a", max_sessions_for_invite=1)

    manager.create("invite-b", max_sessions_for_invite=1)


def test_turn_input_and_rate_limits():
    manager = make_manager(max_turns=1, max_input_chars=5, requests_per_minute=2)
    session = manager.create("invite-a")

    with pytest.raises(InputTooLongError):
        manager.check_input(session, "123456")

    manager.check_input(session, "12345")
    manager.check_turn(session)
    manager.record_exchange(session, "hello", "world")
    with pytest.raises(TurnLimitError):
        manager.check_turn(session)

    other = manager.create("invite-b")
    manager.note_request(other)
    manager.note_request(other)
    with pytest.raises(SessionRateLimitError):
        manager.note_request(other)


def test_end_and_expiry_tombstones():
    clock = Clock()
    manager = make_manager(clock=clock)
    ended = manager.create("invite-a")
    manager.end(ended.id)

    with pytest.raises(SessionEndedError):
        manager.get(ended.id)

    expiring = manager.create("invite-b")
    clock.advance(minutes=31)
    with pytest.raises(SessionExpiredError):
        manager.get(expiring.id)

    clock.advance(seconds=301)
    with pytest.raises(SessionNotFoundError):
        manager.get(ended.id)
    with pytest.raises(SessionNotFoundError):
        manager.get(expiring.id)


def test_idle_timeout_marks_expired():
    clock = Clock()
    manager = make_manager(clock=clock, ttl=timedelta(hours=2))
    session = manager.create("invite-a")
    clock.advance(minutes=11)

    with pytest.raises(SessionExpiredError):
        manager.get(session.id)


def test_list_metadata_has_no_message_content():
    manager = make_manager()
    session = manager.create("invite-a")
    manager.record_exchange(session, "secret user text", "secret reply")

    metadata = manager.list_metadata()
    assert metadata[0]["id"] == session.id
    assert metadata[0]["turns"] == 1
    assert "secret user text" not in repr(metadata)
    assert "secret reply" not in repr(metadata)
