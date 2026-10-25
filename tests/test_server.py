from __future__ import annotations

import hashlib
from datetime import timedelta

import httpx
import pytest

from person_simulator.config import load_settings
from person_simulator.errors import InviteError
from person_simulator.providers.mock import MockClient
from person_simulator.runtime.models import RuntimePersona
from person_simulator.server import create_server
from person_simulator.server.registry import InviteRegistry
from person_simulator.storage import utcnow


class Clock:
    def __init__(self) -> None:
        self.now = utcnow()

    def __call__(self):
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def make_persona() -> RuntimePersona:
    prompt = "你是 A。这是 AI 模拟，不是本人。"
    return RuntimePersona(
        run_id="run-test",
        strategy="evidence",
        package_version="0.1.0",
        prompt_version="1.0",
        source_hash="a" * 64,
        target="A",
        interlocutor="B",
        system_prompt=prompt,
        system_prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        original_system_prompt_sha256="b" * 64,
        is_mock=True,
        created_at=utcnow(),
    )


@pytest.fixture
def server():
    settings = load_settings(env={})
    settings.simulation.allowed_hosts = ["127.0.0.1", "localhost", "::1"]
    registry = InviteRegistry()
    instance = create_server(
        persona=make_persona(),
        settings=settings,
        host="127.0.0.1",
        port=0,
        registry=registry,
        admin_token="admin-token",
        client=MockClient(),
    )
    instance.start()
    try:
        yield instance
    finally:
        instance.shutdown()


def exchange(server, token: str) -> httpx.Client:
    client = httpx.Client(
        base_url=server.public_url, follow_redirects=False, trust_env=False
    )
    response = client.get("/", params={"token": token})
    assert response.status_code == 303
    return client


def test_registry_roundtrip_and_token_not_in_metadata():
    registry = InviteRegistry()
    record, token = registry.create("friend", timedelta(minutes=5), 2)

    assert registry.validate(token).id == record.id
    metadata = registry.list_metadata()
    assert metadata[0]["id"] == record.id
    assert token not in repr(metadata)
    assert "token" not in metadata[0]


def test_registry_revoke_and_expire():
    clock = Clock()
    registry = InviteRegistry(clock=clock)
    record, token = registry.create("friend", timedelta(minutes=5), 1)

    registry.revoke(record.id)
    with pytest.raises(InviteError):
        registry.validate(token)

    record2, token2 = registry.create("other", timedelta(minutes=5), 1)
    clock.advance(minutes=6)
    with pytest.raises(InviteError):
        registry.validate(token2)
    assert record2.id in repr(registry.list_metadata())


def test_token_exchange_and_chat_roundtrip(server):
    token = server.registry.create("friend", timedelta(minutes=5), 2)[1]
    client = exchange(server, token)

    response = client.post("/api/chat", json={"message": "在吗"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"]
    assert body["turn"] == 1
    assert any("MOCK" in notice for notice in body["notices"])


def test_static_ui_discloses_ai_and_has_no_download(server):
    client = httpx.Client(base_url=server.public_url, trust_env=False)

    index = client.get("/")
    assert index.status_code == 200
    assert "AI 模拟角色，不是本人" in index.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_no_profile_or_run_files_exposed(server):
    client = httpx.Client(base_url=server.public_url, trust_env=False)

    for path in (
        "/persona.json",
        "/system_prompt.md",
        "/api/persona",
        "/api/profile",
        "/runs/run-test/persona.json",
    ):
        assert client.get(path).status_code == 404


def test_admin_is_not_on_public_listener(server):
    client = httpx.Client(base_url=server.public_url, trust_env=False)
    assert client.get("/admin/sessions").status_code == 404


def test_admin_listener_requires_token(server):
    admin = httpx.Client(base_url=server.admin_url, trust_env=False)

    assert admin.get("/admin/sessions").status_code == 401
    response = admin.get(
        "/admin/sessions", headers={"X-PSIM-Admin": server.admin_token}
    )
    assert response.status_code == 200
    assert response.json() == []


def test_admin_creates_and_revokes_invite(server):
    admin = httpx.Client(base_url=server.admin_url, trust_env=False)
    headers = {"X-PSIM-Admin": server.admin_token}

    created = admin.post(
        "/admin/invites",
        headers=headers,
        json={"label": "friend", "expires_in_seconds": 300, "max_sessions": 1},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["token"]
    assert payload["invite_id"]

    client = exchange(server, payload["token"])
    assert client.post("/api/chat", json={"message": "hello"}).status_code == 200

    revoked = admin.delete(
        f"/admin/invites/{payload['invite_id']}", headers=headers
    )
    assert revoked.status_code == 204

    blocked = httpx.Client(
        base_url=server.public_url, follow_redirects=False, trust_env=False
    )
    assert blocked.get("/", params={"token": payload["token"]}).status_code == 401


def test_host_header_rejected(server):
    client = httpx.Client(base_url=server.public_url, trust_env=False)
    response = client.get("/healthz", headers={"Host": "evil.example"})
    assert response.status_code == 403


def test_two_sessions_are_isolated(server):
    token = server.registry.create("friend", timedelta(minutes=5), 2)[1]
    first = exchange(server, token)
    second = exchange(server, token)

    first.post("/api/chat", json={"message": "first session"})
    first_meta = first.get("/api/session").json()
    second_meta = second.get("/api/session").json()

    assert first_meta["id"] != second_meta["id"]
    assert first_meta["turns"] == 1
    assert second_meta["turns"] == 0


def test_end_session_then_chat_is_gone(server):
    token = server.registry.create("friend", timedelta(minutes=5), 1)[1]
    client = exchange(server, token)

    ended = client.post("/api/session/end")
    assert ended.status_code == 204

    response = client.post("/api/chat", json={"message": "again"})
    assert response.status_code == 410
