from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from person_simulator.cli import main
from person_simulator.config import load_settings
from person_simulator.errors import RunIncompleteError
from person_simulator.pipeline import build_run
from person_simulator.providers.mock import MockClient
from person_simulator.runtime.persona import load_runtime_persona
from person_simulator.server import InviteRegistry, create_server
from person_simulator.wholechat.pipeline import simulate_run

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
    return build_run(
        chat,
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
    ).run_dir


def start_server(run: Path):
    loaded = load_runtime_persona(run)
    settings = load_settings(env={})
    settings.simulation.allowed_hosts = ["127.0.0.1", "localhost", "::1"]
    server = create_server(
        persona=loaded.persona,
        settings=settings,
        host="127.0.0.1",
        port=0,
        registry=InviteRegistry(),
        admin_token="admin-token",
        client=MockClient(),
        replay_messages=loaded.replay_messages,
    )
    server.start()
    return server


def test_build_mock_then_serve_chat_then_end(tmp_path):
    run = make_run(tmp_path)
    server = start_server(run)
    try:
        token = server.registry.create("e2e", timedelta(minutes=5), 1)[1]
        client = httpx.Client(
            base_url=server.public_url, follow_redirects=False, trust_env=False
        )
        exchanged = client.get("/", params={"token": token})
        assert exchanged.status_code == 303

        reply = client.post("/api/chat", json={"message": "在吗"})
        assert reply.status_code == 200
        assert "MOCK" in reply.json()["reply"]

        assert client.post("/api/session/end").status_code == 204
        assert client.post("/api/chat", json={"message": "again"}).status_code == 410
        assert client.get("/persona.json").status_code == 404
        assert client.get("/system_prompt.md").status_code == 404
    finally:
        server.shutdown()


def test_failed_run_cannot_be_served(tmp_path, capsys):
    run = make_run(tmp_path)
    data = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    data["analysis_status"] = "failed"
    data["export_status"] = "failed"
    (run / "manifest.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RunIncompleteError):
        load_runtime_persona(run)

    code = main(["serve", "--run", str(run), "--mode", "mock", "--check"])
    assert code == 4
    assert "E_RUN_INCOMPLETE" in capsys.readouterr().err


def test_legacy_simulate_rejects_failed_run(tmp_path):
    run = make_run(tmp_path)
    data = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    data["analysis_status"] = "failed"
    data["export_status"] = "failed"
    (run / "manifest.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RunIncompleteError):
        simulate_run(
            run,
            "在吗",
            settings=load_settings(env={}),
            client=MockClient(),
        )
