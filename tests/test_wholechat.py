from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from person_simulator.config import load_settings
from person_simulator.errors import EvidenceError, ResponseFormatError
from person_simulator.models import Message
from person_simulator.providers.base import ModelResponse
from person_simulator.providers.mock import MockClient
from person_simulator.wholechat.pipeline import build_whole, simulate_run, whole_fits
from person_simulator.wholechat.transcript import render_message, serialize_transcript
from person_simulator.wholechat.verify import extract_tag, verify_whole_output

CHAT = """A: 早，今天出门吗？
B: 看情况。
  如果不下雨就去。
A: 那带上伞。
B: 好。
A: 最近有点累。
B: 早点睡。
"""


def _settings(tmp_path: Path):
    return load_settings(config_path=None, cli_overrides={}, env={})


def _chat(tmp_path: Path) -> Path:
    path = tmp_path / "chat.txt"
    path.write_text(CHAT, encoding="utf-8")
    return path


def _message(index: int, speaker: str, text: str) -> Message:
    return Message(
        id=f"m{index:06d}",
        index=index - 1,
        speaker=speaker,
        text=text,
        timestamp=datetime(2025, 6, 10, 18, index, tzinfo=timezone.utc),
        line_start=index,
        line_end=index,
        session_id="s001",
    )


def test_render_message_preserves_multiline_and_timestamp():
    message = _message(1, "A", "第一行\n第二行")
    line = render_message(message)
    assert line.startswith("[m000001] 2025-06-10 18:01:00+00:00 A: 第一行\n")
    assert "  第二行" in line


def test_serialize_transcript_limit_and_stats():
    messages = [_message(1, "A", "一"), _message(2, "B", "二")]
    transcript = serialize_transcript(messages, limit=1)
    assert transcript.message_count == 1
    assert transcript.limited
    assert transcript.first_message_id == "m000001"
    assert transcript.last_message_id == "m000001"
    assert transcript.estimated_tokens > 0


def test_extract_tag_and_missing_tag():
    text = "<system_prompt>abc</system_prompt><person_simulation>def</person_simulation>"
    assert extract_tag(text, "system_prompt") == "abc"
    assert extract_tag(text, "missing") is None


def test_verify_message_refs_rejects_missing():
    messages = {"m000001": _message(1, "A", "一")}
    with pytest.raises(EvidenceError):
        verify_whole_output(
            response_text="[m999999]",
            system_prompt="[m999999]",
            profile=None,
            messages=messages,
            is_mock=False,
        )


class FakeWholeClient:
    provider = "fake"
    is_mock = False

    def __init__(self, content: str):
        self.content = content
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return ModelResponse(
            content=self.content,
            finish_reason="stop",
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            provider=self.provider,
            is_mock=False,
        )


def test_build_whole_writes_outputs_and_manifest(tmp_path):
    settings = _settings(tmp_path)
    result = build_whole(
        _chat(tmp_path),
        target="A",
        settings=settings,
        out_root=tmp_path / "runs",
        client=MockClient(),
    )
    assert result.manifest["status"] == "complete"
    assert result.transcript.message_count == 6
    assert result.system_prompt_path.is_file()
    assert "MOCK" in result.system_prompt_path.read_text(encoding="utf-8")
    assert result.profile_path and result.profile_path.is_file()
    assert result.report_path.is_file()
    assert not (result.run_dir / "transcript.txt").exists()
    report = result.report_path.read_text(encoding="utf-8")
    assert "actual prompt tokens" in report
    assert "strategy: whole" in report


def test_build_whole_accepts_tagged_fake_response(tmp_path):
    content = (
        "<system_prompt>\nMOCK 直接以 A 的口吻回复。[m000001]\n</system_prompt>\n"
        "<person_simulation>\nMOCK 材料：A 句子短。\n</person_simulation>"
    )
    result = build_whole(
        _chat(tmp_path),
        target="A",
        settings=_settings(tmp_path),
        out_root=tmp_path / "runs",
        client=FakeWholeClient(content),
    )
    assert result.manifest["usage"]["prompt_tokens"] == 100
    assert "[m000001]" in result.system_prompt_path.read_text(encoding="utf-8")


def test_build_whole_missing_tag_fails(tmp_path):
    with pytest.raises(ResponseFormatError):
        build_whole(
            _chat(tmp_path),
            target="A",
            settings=_settings(tmp_path),
            out_root=tmp_path / "runs",
            client=FakeWholeClient("no tags here"),
        )


def test_whole_fits_and_simulate_run(tmp_path):
    settings = _settings(tmp_path)
    parsed = __import__("person_simulator.parser", fromlist=["parse_chat"]).parse_chat(
        _chat(tmp_path), target="A"
    )
    fits, transcript = whole_fits(parsed, settings)
    assert fits
    assert transcript.message_count == 6

    result = build_whole(
        _chat(tmp_path),
        target="A",
        settings=settings,
        out_root=tmp_path / "runs",
        client=MockClient(),
    )
    reply = simulate_run(result.run_dir, "在吗？", settings=settings, client=MockClient())
    assert "MOCK" in reply
