from __future__ import annotations

import json
from pathlib import Path

import pytest

from person_simulator.cli import main
from person_simulator.config import load_settings
from person_simulator.errors import InterruptedError
from person_simulator.pipeline import build_run, render_run
from person_simulator.progress import ProgressEvent
from person_simulator.providers.base import ModelRequest
from person_simulator.providers.mock import MockClient
from person_simulator.providers.runner import RequestRunner
from person_simulator.wholechat.pipeline import build_whole

CHAT = """A: 早，今天出门吗？
B: 看情况。
A: 那带上伞。
B: 好。
A: 最近有点累。
B: 那就早点睡。
"""


def _chat(tmp_path: Path) -> Path:
    path = tmp_path / "chat.txt"
    path.write_text(CHAT, encoding="utf-8")
    return path


def test_progress_event_is_json_safe():
    event = ProgressEvent(
        stage="extract",
        message="处理分片",
        current=1,
        total=3,
        task_id="extract:c1",
        requests_used=2,
    )

    assert event.as_dict() == {
        "stage": "extract",
        "message": "处理分片",
        "current": 1,
        "total": 3,
        "task_id": "extract:c1",
        "requests_used": 2,
    }


def test_request_runner_emits_request_events():
    events: list[ProgressEvent] = []
    runner = RequestRunner(
        MockClient(),
        max_attempts=1,
        max_requests=5,
        progress=events.append,
    )

    runner.call(
        ModelRequest(
            task_id="test",
            messages=[{"role": "user", "content": "hi"}],
            output_limit=16,
        )
    )

    assert [event.stage for event in events] == ["request", "request"]
    assert events[0].message == "start"
    assert events[1].message == "done"
    assert events[1].requests_used == 1
    assert events[1].task_id == "test"


def test_build_run_emits_stages(tmp_path):
    events: list[ProgressEvent] = []

    build_run(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
        progress=events.append,
    )

    stages = {event.stage for event in events}
    assert {"parse", "plan", "extract", "reduce", "render", "export", "complete"} <= stages
    for event in events:
        assert event.message
        assert "\n" not in event.message


def test_build_run_cancellation_leaves_no_formal_export(tmp_path):
    output = tmp_path / "runs"

    def cancel(event: ProgressEvent) -> None:
        if event.stage == "extract":
            raise InterruptedError("用户取消", stage="progress")

    with pytest.raises(InterruptedError):
        build_run(
            _chat(tmp_path),
            target="A",
            settings=load_settings(env={}),
            out_root=output,
            progress=cancel,
        )

    run_dir = next(output.iterdir())
    assert not (run_dir / "person_simulation.md").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["analysis_status"] == "incomplete"
    assert manifest["export_status"] == "failed"


def test_build_whole_emits_stages(tmp_path):
    events: list[ProgressEvent] = []

    build_whole(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
        progress=events.append,
    )

    stages = {event.stage for event in events}
    assert {"parse", "analyze", "verify", "export", "complete"} <= stages


def test_render_run_emits_stages(tmp_path):
    result = build_run(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
    )
    events: list[ProgressEvent] = []

    render_run(result.run_dir, tmp_path / "export", progress=events.append)

    assert {"render", "export"} <= {event.stage for event in events}


def test_cli_json_progress_writes_json_lines_to_stderr(tmp_path, capsys):
    code = main(
        [
            "build",
            "--input",
            str(_chat(tmp_path)),
            "--target",
            "A",
            "--mode",
            "mock",
            "--strategy",
            "evidence",
            "--out",
            str(tmp_path / "runs"),
            "--json-progress",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "progress " not in captured.out
    lines = [line for line in captured.err.splitlines() if line.startswith("{")]
    assert lines
    events = [json.loads(line) for line in lines]
    assert {"stage", "message", "current", "total", "task_id", "requests_used"} == set(
        events[0]
    )
    assert any(event["stage"] == "complete" for event in events)
