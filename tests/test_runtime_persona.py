from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from person_simulator.errors import (
    RunHashError,
    RunIncompleteError,
    RunNotFoundError,
    RunVersionError,
)
from person_simulator.models import (
    AnalysisStatus,
    Coverage,
    ExportStatus,
    Manifest,
    Message,
    Persona,
    QualityStatus,
)
from person_simulator.storage import utcnow
from person_simulator.runtime import Audience, load_runtime_persona


SOURCE_HASH = hashlib.sha256(b"synthetic chat").hexdigest()


def _coverage() -> Coverage:
    return Coverage(
        source_hash=SOURCE_HASH,
        total_messages=2,
        target_messages=1,
        total_chars=10,
        covered_chars=10,
        ratio=1.0,
        complete=True,
        core_part_ids=["m000001:p1"],
    )


def _messages() -> list[Message]:
    return [
        Message(
            id="m000001",
            index=0,
            speaker="A",
            text="原 system prompt",
            line_start=1,
            line_end=1,
            session_id="s001",
        ),
        Message(
            id="m000002",
            index=1,
            speaker="B",
            text="这是一条足够长的原始聊天消息，用来测试复述检测。",
            line_start=2,
            line_end=2,
            session_id="s001",
        ),
    ]


def make_evidence_run(tmp_path: Path, *, status: str = "complete") -> Path:
    run = tmp_path / "run-test"
    run.mkdir(parents=True, exist_ok=True)
    complete = status == "complete"
    manifest = Manifest(
        prompt_version="1.0",
        package_version="0.1.0",
        run_id=run.name,
        source_hash=SOURCE_HASH,
        target="A",
        interlocutor="B",
        config_hash="0" * 64,
        provider="mock",
        model=None,
        is_mock=True,
        analysis_status=AnalysisStatus.COMPLETE if complete else AnalysisStatus.FAILED,
        quality_status=QualityStatus.NOT_EVALUATED,
        export_status=ExportStatus.COMPLETE if complete else ExportStatus.FAILED,
        coverage=_coverage(),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    persona = Persona(
        target="A",
        interlocutor="B",
        source_hash=SOURCE_HASH,
        coverage=_coverage(),
    )
    (run / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "persona.json").write_text(
        json.dumps(persona.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "system_prompt.md").write_text("原 system prompt：你是 A。\n", encoding="utf-8")
    rows = [
        json.dumps(message.model_dump(mode="json"), ensure_ascii=False)
        for message in _messages()
    ]
    (run / "messages.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return run


def make_whole_run(
    tmp_path: Path,
    *,
    status: str = "complete",
    with_messages: bool = False,
    package_version: str | None = None,
) -> Path:
    run = tmp_path / "whole-run-test"
    run.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "whole-1.0",
        "strategy": "whole",
        "run_id": run.name,
        "source_hash": SOURCE_HASH,
        "target": "A",
        "interlocutor": "B",
        "is_mock": True,
        "message_count": 2,
        "char_count": 20,
        "status": status,
        "created_at": utcnow().isoformat(),
        "updated_at": utcnow().isoformat(),
    }
    if package_version is not None:
        manifest["package_version"] = package_version
    (run / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (run / "system_prompt.md").write_text("原 whole prompt：你是 A。\n", encoding="utf-8")
    if with_messages:
        rows = [
            json.dumps(message.model_dump(mode="json"), ensure_ascii=False)
            for message in _messages()
        ]
        (run / "messages.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return run


def test_load_evidence_run_composes_prompt(tmp_path):
    run = make_evidence_run(tmp_path)
    loaded = load_runtime_persona(run)

    assert loaded.persona.schema_version == "runtime-persona-1.0"
    assert loaded.persona.strategy == "evidence"
    assert loaded.persona.audience == Audience.GUEST
    assert "AI 模拟" in loaded.persona.system_prompt
    assert "原 system prompt" in loaded.persona.system_prompt
    assert "访客" in loaded.persona.system_prompt
    assert loaded.persona.system_prompt_sha256 == hashlib.sha256(
        loaded.persona.system_prompt.encode("utf-8")
    ).hexdigest()
    assert loaded.persona.replay_guard == "full"
    assert loaded.replay_messages
    assert loaded.persona.is_mock is True


def test_load_whole_run_without_messages(tmp_path):
    run = make_whole_run(tmp_path)
    loaded = load_runtime_persona(run)

    assert loaded.persona.strategy == "whole"
    assert loaded.persona.replay_guard == "prompt_only"
    assert loaded.replay_messages == ()
    assert "原 whole prompt" in loaded.persona.system_prompt


def test_whole_run_with_messages_uses_full_replay_guard(tmp_path):
    run = make_whole_run(tmp_path, with_messages=True)
    loaded = load_runtime_persona(run)

    assert loaded.persona.replay_guard == "full"
    assert len(loaded.replay_messages) == 2


def test_rejects_failed_or_incomplete_run(tmp_path):
    for status in ("failed", "running"):
        run = make_evidence_run(tmp_path, status=status)
        with pytest.raises(RunIncompleteError):
            load_runtime_persona(run)


def test_rejects_missing_persona_or_prompt(tmp_path):
    run = make_evidence_run(tmp_path)
    (run / "persona.json").unlink()
    with pytest.raises(RunIncompleteError):
        load_runtime_persona(run)

    run = make_evidence_run(tmp_path / "second")
    (run / "system_prompt.md").unlink()
    with pytest.raises(RunIncompleteError):
        load_runtime_persona(run)


def test_rejects_source_hash_mismatch(tmp_path):
    run = make_evidence_run(tmp_path)
    data = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    data["source_hash"] = "0" * 64
    (run / "manifest.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RunHashError):
        load_runtime_persona(run)


def test_guest_and_original_prompts_differ(tmp_path):
    run = make_evidence_run(tmp_path)
    guest = load_runtime_persona(run, audience=Audience.GUEST).persona.system_prompt
    original = load_runtime_persona(run, audience=Audience.ORIGINAL).persona.system_prompt

    assert guest != original
    assert "访客" in guest
    assert "原对话对象" in original


def test_rejects_unknown_whole_package_version(tmp_path):
    run = make_whole_run(tmp_path, package_version="9.9.9")
    with pytest.raises(RunVersionError):
        load_runtime_persona(run)


def test_rejects_unknown_schema_version(tmp_path):
    run = make_evidence_run(tmp_path)
    data = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    data["schema_version"] = "9.9"
    (run / "manifest.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RunVersionError):
        load_runtime_persona(run)


def test_rejects_missing_run_directory(tmp_path):
    with pytest.raises(RunNotFoundError):
        load_runtime_persona(tmp_path / "does-not-exist")
