from __future__ import annotations

import json
from pathlib import Path

import pytest

from person_simulator.cli import main
from person_simulator.config import load_settings
from person_simulator.errors import InputError, RunIncompleteError
from person_simulator.pipeline import build_run
from person_simulator.runtime.persona import load_runtime_persona
from person_simulator.wholechat.pipeline import build_whole

CHAT = """A: 早，今天出门吗？
B: 看情况。
A: 那带上伞。
B: 好。
A: 最近有点累。
B: 那就早点睡。
"""


def _chat(tmp_path: Path, text: str = CHAT) -> Path:
    path = tmp_path / "chat.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_evidence_limit_messages_marks_pilot_and_truncates_stored_messages(tmp_path):
    result = build_run(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
        limit_messages=4,
    )

    assert result.report["limited"] is True
    assert result.report["source_messages"] == 6
    assert result.report["analyzed_messages"] == 4
    assert len((result.run_dir / "messages.jsonl").read_text(encoding="utf-8").splitlines()) == 4
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["budget"]["limit_messages"] == 4
    assert manifest["budget"]["source_message_count"] == 6
    assert manifest["budget"]["analyzed_message_count"] == 4
    report = (result.run_dir / "build_report.md").read_text(encoding="utf-8")
    assert "pilot" in report.lower()
    assert "4/6" in report
    assert "PILOT" in result.export_path.read_text(encoding="utf-8")


def test_evidence_limit_at_least_total_is_not_limited(tmp_path):
    result = build_run(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
        limit_messages=6,
    )

    assert result.report["limited"] is False
    assert result.report["source_messages"] == 6
    assert result.report["analyzed_messages"] == 6


def test_evidence_limit_must_keep_both_speakers(tmp_path):
    one_speaker = "A: 一\nA: 二\nA: 三\nB: 四\n"

    with pytest.raises(InputError):
        build_run(
            _chat(tmp_path, one_speaker),
            target="A",
            settings=load_settings(env={}),
            out_root=tmp_path / "runs",
            limit_messages=2,
        )


def test_evidence_limit_rejects_non_positive(tmp_path):
    with pytest.raises(InputError):
        build_run(
            _chat(tmp_path),
            target="A",
            settings=load_settings(env={}),
            out_root=tmp_path / "runs",
            limit_messages=0,
        )


def test_cli_build_evidence_limit_prints_pilot_summary(tmp_path, capsys):
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
            "--limit-messages",
            "4",
            "--out",
            str(tmp_path / "runs"),
        ]
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "limited true" in output
    assert "source_messages 6" in output
    assert "analyzed_messages 4" in output


def test_evidence_pilot_cannot_be_loaded_as_runtime_persona(tmp_path):
    result = build_run(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
        limit_messages=4,
    )

    with pytest.raises(RunIncompleteError):
        load_runtime_persona(result.run_dir)


def test_whole_limit_rejects_non_positive(tmp_path):
    with pytest.raises(InputError):
        build_whole(
            _chat(tmp_path),
            target="A",
            settings=load_settings(env={}),
            out_root=tmp_path / "runs",
            limit_messages=0,
        )


def test_whole_pilot_cannot_be_loaded_as_runtime_persona(tmp_path):
    result = build_whole(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
        limit_messages=2,
    )

    with pytest.raises(RunIncompleteError):
        load_runtime_persona(result.run_dir)
