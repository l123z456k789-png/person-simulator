from __future__ import annotations

import json
from pathlib import Path

import pytest

from person_simulator.cli import main
from person_simulator.config import load_settings
from person_simulator.errors import PrivacyError
from person_simulator.pipeline import build_run, render_run
from person_simulator.providers.base import ModelResponse
from person_simulator.wholechat.pipeline import build_whole

CHAT = """A: 我的手机是13800138000。
B: 好。
A: 邮箱是person@example.com。
B: 嗯。
A: 再说一次13800138000。
B: 知道了。
"""


def _chat(tmp_path: Path) -> Path:
    path = tmp_path / "chat.txt"
    path.write_text(CHAT, encoding="utf-8")
    return path


class PiiWholeClient:
    provider = "mock"
    is_mock = True

    def complete(self, request):
        return ModelResponse(
            content=(
                "<system_prompt>MOCK 电话 13800138000</system_prompt>"
                "<person_simulation>MOCK 邮箱 person@example.com</person_simulation>"
            ),
            finish_reason="stop",
            usage={},
            request_id="fake",
            provider="mock",
            is_mock=True,
        )


def test_build_warn_reports_pii_without_redacting(tmp_path):
    result = build_run(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
        privacy_mode="warn",
    )

    assert result.report["privacy"]["total"] >= 2
    combined = (
        result.export_path.read_text(encoding="utf-8")
        + (result.system_prompt_path.read_text(encoding="utf-8") if result.system_prompt_path else "")
    )
    assert "13800138000" in combined
    assert "13800138000" in (result.run_dir / "messages.jsonl").read_text(encoding="utf-8")


def test_build_redact_pii_changes_exports_but_keeps_run_raw(tmp_path):
    result = build_run(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
        privacy_mode="redact",
    )

    export = result.export_path.read_text(encoding="utf-8")
    prompt = result.system_prompt_path.read_text(encoding="utf-8")
    assert "13800138000" not in export
    assert "13800138000" not in prompt
    assert "person@example.com" not in export
    assert "person@example.com" not in prompt
    assert "[已隐藏]" in export or "[已隐藏]" in prompt
    assert result.report["privacy"]["total"] >= 2

    # The private run directory still keeps the original messages for evidence
    # and resume; only the shareable exports are redacted.
    assert "13800138000" in (result.run_dir / "messages.jsonl").read_text(encoding="utf-8")


def test_build_privacy_strict_blocks_formal_export(tmp_path):
    output = tmp_path / "runs"
    with pytest.raises(PrivacyError):
        build_run(
            _chat(tmp_path),
            target="A",
            settings=load_settings(env={}),
            out_root=output,
            privacy_mode="block",
        )

    run_dir = next(output.iterdir())
    assert not (run_dir / "person_simulation.md").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["analysis_status"] == "incomplete"
    assert manifest["export_status"] == "failed"


def test_render_redact_pii(tmp_path):
    result = build_run(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
    )
    destination = tmp_path / "export"
    path = render_run(
        result.run_dir,
        destination,
        privacy_mode="redact",
    )

    text = path.read_text(encoding="utf-8")
    assert "13800138000" not in text
    assert "person@example.com" not in text


def test_whole_build_redacts_exports(tmp_path):
    result = build_whole(
        _chat(tmp_path),
        target="A",
        settings=load_settings(env={}),
        out_root=tmp_path / "runs",
        privacy_mode="redact",
        client=PiiWholeClient(),
    )

    text = result.system_prompt_path.read_text(encoding="utf-8")
    assert "13800138000" not in text
    assert result.manifest["privacy"]["total"] >= 1


def test_cli_build_redact_pii_prints_safe_summary(tmp_path, capsys):
    output = tmp_path / "runs"
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
            str(output),
            "--redact-pii",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "privacy_redacted" in captured.out
    assert "13800138000" not in captured.out
    assert "person@example.com" not in captured.err
