from __future__ import annotations

from pathlib import Path

import pytest

from person_simulator.cli import main
from person_simulator.config import load_settings
from person_simulator.pipeline import build_run
from person_simulator.providers.mock import MockClient
from person_simulator.runtime.invite import read_invite
from person_simulator.runtime.persona import load_runtime_persona
from person_simulator.server import InviteRegistry, create_server

CHAT = """A: 早，今天出门吗？
B: 看情况。
A: 那带上伞。
B: 好。
A: 最近有点累。
B: 那就早点睡。
"""


def make_run(tmp_path: Path) -> Path:
    chat = tmp_path / "chat.txt"
    chat.write_text(CHAT, encoding="utf-8")
    result = build_run(
        chat,
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
    )
    return result.run_dir


@pytest.fixture
def server(tmp_path):
    run = make_run(tmp_path)
    loaded = load_runtime_persona(run)
    settings = load_settings(env={})
    settings.simulation.allowed_hosts = ["127.0.0.1", "localhost", "::1"]
    instance = create_server(
        persona=loaded.persona,
        settings=settings,
        host="127.0.0.1",
        port=0,
        registry=InviteRegistry(),
        admin_token="admin-token",
        client=MockClient(),
        replay_messages=loaded.replay_messages,
    )
    instance.start()
    try:
        yield instance
    finally:
        instance.shutdown()


def test_serve_check_validates_run(tmp_path, capsys):
    run = make_run(tmp_path)

    code = main(["serve", "--run", str(run), "--mode", "mock", "--check"])

    assert code == 0
    output = capsys.readouterr().out
    assert "runtime-persona-1.0" in output
    assert "status ready" in output


@pytest.mark.parametrize(
    "extra",
    [
        ["--max-turns", "0"],
        ["--max-sessions", "0"],
        ["--max-input-chars", "-1"],
        ["--port", "99999"],
    ],
)
def test_serve_check_rejects_invalid_simulation_values(tmp_path, capsys, extra):
    run = make_run(tmp_path)

    code = main(
        ["serve", "--run", str(run), "--mode", "mock", "--check", *extra]
    )

    assert code == 2
    assert "simulation" in capsys.readouterr().err.lower()


def test_serve_check_rejects_oversized_runtime_prompt(tmp_path, capsys):
    run = make_run(tmp_path)
    (run / "system_prompt.md").write_text("x" * 10_000, encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text("[mock]\ncontext_window = 1000\n", encoding="utf-8")

    code = main(
        [
            "serve",
            "--run",
            str(run),
            "--mode",
            "mock",
            "--config",
            str(config),
            "--check",
        ]
    )

    assert code == 2
    assert "上下文预算" in capsys.readouterr().err


def test_serve_check_rejects_public_bind_without_allow_lan(tmp_path, capsys):
    run = make_run(tmp_path)

    code = main(
        [
            "serve",
            "--run",
            str(run),
            "--mode",
            "mock",
            "--host",
            "0.0.0.0",
            "--check",
        ]
    )

    assert code == 2
    assert "--allow-lan" in capsys.readouterr().err


def test_admin_client_rejects_non_loopback():
    from person_simulator.errors import ClientError
    from person_simulator.runtime.client import AdminClient

    with pytest.raises(ClientError):
        AdminClient("https://example.test", "admin-token")


def test_invite_create_and_connect(server, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PSIM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("PSIM_INVITE_PASSPHRASE", "test-passphrase")
    out = tmp_path / "invite.psim"

    code = main(
        [
            "invite",
            "create",
            "--server",
            server.admin_url,
            "--endpoint",
            server.public_url,
            "--out",
            str(out),
            "--label",
            "friend",
            "--expires-in",
            "300",
            "--max-sessions",
            "2",
        ]
    )

    assert code == 0
    created_output = capsys.readouterr().out
    assert "web_url" in created_output
    assert "invite_id" in created_output
    payload = read_invite(out, "test-passphrase")
    assert payload.token
    assert payload.endpoint == server.public_url
    assert main(["invite", "list", "--server", server.admin_url]) == 0
    assert "revoked=False" in capsys.readouterr().out

    code = main(
        [
            "connect",
            "--invite",
            str(out),
            "--message",
            "在吗",
        ]
    )

    assert code == 0
    assert "MOCK" in capsys.readouterr().out


def test_invite_create_refuses_existing_file(server, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PSIM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("PSIM_INVITE_PASSPHRASE", "test-passphrase")
    out = tmp_path / "invite.psim"
    out.write_text("keep me", encoding="utf-8")

    code = main(
        [
            "invite",
            "create",
            "--server",
            server.admin_url,
            "--endpoint",
            server.public_url,
            "--out",
            str(out),
            "--expires-in",
            "300",
        ]
    )

    assert code == 5
    assert out.read_text(encoding="utf-8") == "keep me"
    assert server.registry.list_metadata() == []


def test_session_list_and_delete(server, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PSIM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("PSIM_INVITE_PASSPHRASE", "test-passphrase")
    out = tmp_path / "invite.psim"
    assert (
        main(
            [
                "invite",
                "create",
                "--server",
                server.admin_url,
                "--endpoint",
                server.public_url,
                "--out",
                str(out),
                "--expires-in",
                "300",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["connect", "--invite", str(out), "--message", "hi"]) == 0
    capsys.readouterr()

    assert main(["session", "list", "--server", server.admin_url]) == 0
    listed = capsys.readouterr().out
    assert "state=ended" in listed

    session_id = server.manager.list_metadata()[0]["id"]
    assert (
        main(
            [
                "session",
                "delete",
                "--server",
                server.admin_url,
                str(session_id),
            ]
        )
        == 0
    )
    assert server.manager.list_metadata() == []
