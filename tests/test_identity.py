from __future__ import annotations

import pytest

from person_simulator.errors import InputError
from person_simulator.parser import parse_chat


def test_custom_labels_and_target(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("小明: 早\n小红: 早\n", encoding="utf-8")
    parsed = parse_chat(path, "小明", "小红", target="小红")
    assert parsed.messages[0].speaker == "小明"
    assert parsed.messages[0].session_id == "s001"


def test_target_must_match_exactly(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 早\nB: 早\n", encoding="utf-8")
    with pytest.raises(InputError):
        parse_chat(path, target="a")


def test_target_required_by_cli(tmp_path):
    from person_simulator.cli import main

    path = tmp_path / "chat.txt"
    path.write_text("A: 早\nB: 早\n", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["validate", "--input", str(path)])
    assert error.value.code == 2


def test_labels_must_differ():
    from person_simulator.parser import validate_labels

    with pytest.raises(InputError):
        validate_labels("A", "A", "A")


def test_labels_reject_colon_bracket_newline():
    from person_simulator.parser import validate_labels

    for label in ("A:B", "A[", "A\nB"):
        with pytest.raises(InputError):
            validate_labels(label, "B", "B")


def test_same_speaker_consecutive_is_valid(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 一\nA: 二\nB: 三\n", encoding="utf-8")
    parsed = parse_chat(path)
    assert [m.speaker for m in parsed.messages] == ["A", "A", "B"]


def test_dont_guess_target_from_order(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("B: 先说话\nA: 后说话\n", encoding="utf-8")
    parsed = parse_chat(path, target="A")
    assert parsed.messages[0].speaker == "B"
