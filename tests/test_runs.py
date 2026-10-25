from __future__ import annotations

import json
from pathlib import Path

import pytest

from person_simulator.cli import main
from person_simulator.config import load_settings
from person_simulator.errors import StorageError
from person_simulator.pipeline import build_run
from person_simulator.providers.mock import MockClient
from person_simulator.providers.runner import RequestRunner
from person_simulator.runs import delete_run, inspect_run, list_runs, purge_runs

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


def _complete_run(tmp_path: Path) -> Path:
    return build_run(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
    ).run_dir


def _failed_run(tmp_path: Path) -> Path:
    output = tmp_path / "runs"
    before = {path.name for path in output.iterdir()} if output.exists() else set()
    with pytest.raises(Exception):
        build_run(
            _chat(tmp_path),
            target="A",
            settings=load_settings(env={}),
            out_root=output,
            runner=RequestRunner(MockClient(), max_attempts=1, max_requests=1),
        )
    created = [path for path in output.iterdir() if path.name not in before]
    assert len(created) == 1
    return created[0]


def test_list_runs_reports_evidence_and_failed_runs(tmp_path):
    complete = _complete_run(tmp_path)
    failed = _failed_run(tmp_path)

    summaries = {summary.run_id: summary for summary in list_runs(tmp_path / "runs")}

    assert complete.name in summaries
    assert failed.name in summaries
    assert summaries[complete.name].status == "complete"
    assert summaries[complete.name].strategy == "evidence"
    assert summaries[failed.name].status == "incomplete"
    assert summaries[complete.name].has_export is True
    assert summaries[failed.name].has_export is False


def test_inspect_run_reports_task_and_file_state(tmp_path):
    run = _complete_run(tmp_path)

    detail = inspect_run(run, root=tmp_path / "runs")

    assert detail.summary.run_id == run.name
    assert detail.summary.status == "complete"
    assert detail.files["manifest.json"] is True
    assert detail.files["person_simulation.md"] is True
    assert detail.files["messages.jsonl"] is True
    assert detail.task_counts.get("succeeded", 0) > 0
    assert "raw chat" not in json.dumps(detail.as_dict(), ensure_ascii=False)


def test_delete_run_refuses_outside_root(tmp_path):
    run = _complete_run(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(StorageError):
        delete_run(run, root=outside)

    assert run.exists()


def test_delete_run_refuses_active_lock(tmp_path):
    run = _complete_run(tmp_path)
    (run / ".lock").write_text(
        json.dumps({"pid": 1, "created_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )

    with pytest.raises(StorageError):
        delete_run(run, root=tmp_path / "runs")

    assert run.exists()


def test_delete_run_removes_completed_run(tmp_path):
    run = _complete_run(tmp_path)

    delete_run(run, root=tmp_path / "runs")

    assert not run.exists()


def test_purge_runs_dry_run_and_apply(tmp_path):
    complete = _complete_run(tmp_path)
    failed = _failed_run(tmp_path)

    selected = purge_runs(
        tmp_path / "runs",
        statuses=("incomplete",),
        apply=False,
    )
    assert [summary.run_id for summary in selected] == [failed.name]
    assert failed.exists()
    assert complete.exists()

    deleted = purge_runs(
        tmp_path / "runs",
        statuses=("incomplete",),
        apply=True,
    )
    assert [summary.run_id for summary in deleted] == [failed.name]
    assert not failed.exists()
    assert complete.exists()


def test_purge_requires_a_filter(tmp_path):
    with pytest.raises(StorageError):
        purge_runs(tmp_path / "runs", apply=False)


def test_purge_refuses_locked_selection_without_partial_delete(tmp_path):
    run = _complete_run(tmp_path)
    (run / ".lock").write_text(
        json.dumps({"pid": 1, "created_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )

    with pytest.raises(StorageError):
        purge_runs(tmp_path / "runs", all_runs=True, apply=True)

    assert run.exists()


def test_cli_runs_list_and_delete_require_yes(tmp_path, capsys):
    run = _complete_run(tmp_path)

    code = main(["runs", "list", "--root", str(tmp_path / "runs"), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["run_id"] == run.name

    code = main(
        ["runs", "delete", run.name, "--root", str(tmp_path / "runs")]
    )
    assert code == 2
    assert run.exists()

    code = main(
        [
            "runs",
            "delete",
            run.name,
            "--root",
            str(tmp_path / "runs"),
            "--yes",
        ]
    )
    assert code == 0
    assert not run.exists()
