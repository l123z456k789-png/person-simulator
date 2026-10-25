from __future__ import annotations

from pathlib import Path

import pytest

from person_simulator.errors import InputError
from person_simulator.parser import parse_chat


def test_basic_messages_and_ids(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 你好\nB: 在吗？\nA: 在。\n", encoding="utf-8")
    parsed = parse_chat(path)
    assert [message.id for message in parsed.messages] == ["m000001", "m000002", "m000003"]
    assert [message.speaker for message in parsed.messages] == ["A", "B", "A"]
    assert [message.text for message in parsed.messages] == ["你好", "在吗？", "在。"]
    assert parsed.messages[0].line_start == 1
    assert parsed.messages[0].line_end == 1


def test_fullwidth_colon_and_single_space(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A：  两个空格\nB:  也是\n", encoding="utf-8")
    parsed = parse_chat(path)
    assert parsed.messages[0].text == " 两个空格"
    assert parsed.messages[1].text == " 也是"


def test_continuation_strips_exactly_two_spaces(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 第一行\n  第二行\n    保留两个空格\nB: 好\n", encoding="utf-8")
    parsed = parse_chat(path)
    assert parsed.messages[0].text == "第一行\n第二行\n  保留两个空格"
    assert parsed.messages[0].line_end == 3


def test_two_space_line_is_body_blank_line(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 第一行\n  \n  第三行\nB: 好\n", encoding="utf-8")
    parsed = parse_chat(path)
    assert parsed.messages[0].text == "第一行\n\n第三行"


def test_indented_header_is_body_text(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 第一行\n  B: 这不是新消息\nB: 真正的新消息\n", encoding="utf-8")
    parsed = parse_chat(path)
    assert len(parsed.messages) == 2
    assert parsed.messages[0].text == "第一行\nB: 这不是新消息"


def test_timestamp_preserves_offset(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("[2024-01-01T10:00:00+08:00] A: 早\nB: 早\n", encoding="utf-8")
    parsed = parse_chat(path)
    assert parsed.messages[0].timestamp is not None
    assert parsed.messages[0].timestamp.utcoffset().total_seconds() == 8 * 3600
    assert parsed.messages[1].timestamp is None
    assert any("部分消息带时间" in warning for warning in parsed.warnings)


def test_out_of_order_warns_without_sorting(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text(
        "[2024-01-01T11:00:00+08:00] A: 后\n"
        "[2024-01-01T10:00:00+08:00] B: 前\n",
        encoding="utf-8",
    )
    parsed = parse_chat(path)
    assert [m.text for m in parsed.messages] == ["后", "前"]
    assert any("非单调" in warning for warning in parsed.warnings)


def test_session_boundary_after_30_minutes(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text(
        "[2024-01-01T10:00:00+08:00] A: 一\n"
        "[2024-01-01T10:10:00+08:00] B: 二\n"
        "[2024-01-01T11:00:00+08:00] A: 三\n"
        "[2024-01-01T11:05:00+08:00] B: 四\n",
        encoding="utf-8",
    )
    parsed = parse_chat(path)
    assert parsed.messages[0].session_id == parsed.messages[1].session_id
    assert parsed.messages[2].session_id != parsed.messages[1].session_id
    assert parsed.messages[2].session_id == parsed.messages[3].session_id


def test_session_boundary_from_blank_line_without_time(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 一\nB: 二\n\nA: 三\nB: 四\n", encoding="utf-8")
    parsed = parse_chat(path)
    assert parsed.messages[0].session_id == parsed.messages[1].session_id
    assert parsed.messages[2].session_id != parsed.messages[1].session_id


def test_blank_lines_with_timestamps_do_not_split_sessions(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text(
        "[2024-01-01T10:00:00] A: 一\n\n"
        "[2024-01-01T10:01:00] B: 二\n\n"
        "[2024-01-01T10:02:00] A: 三\n",
        encoding="utf-8",
    )
    parsed = parse_chat(path)
    assert len({message.session_id for message in parsed.messages}) == 1


def test_bom_and_crlf(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_bytes("\ufeffA: 你好\r\nB: 好\r\n".encode("utf-8"))
    parsed = parse_chat(path)
    assert [m.text for m in parsed.messages] == ["你好", "好"]


def test_unicode_not_stripped_or_normalized(tmp_path):
    path = tmp_path / "chat.txt"
    text = "A:  🙏🏽 你好！！\nB: 嗯\n"
    path.write_text(text, encoding="utf-8")
    parsed = parse_chat(path)
    assert parsed.messages[0].text == " 🙏🏽 你好！！"


def test_invalid_timestamp_reports_line(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("[2024-13-01T10:00:00] A: 你好\nB: 好\n", encoding="utf-8")
    with pytest.raises(InputError) as error:
        parse_chat(path)
    assert "第 1 行" in str(error.value)


def test_unknown_speaker_rejected(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 你好\nC: 第三人\nB: 好\n", encoding="utf-8")
    with pytest.raises(InputError) as error:
        parse_chat(path)
    assert "第 2 行" in str(error.value)
    assert "第三人" not in str(error.value)


def test_unattributed_text_rejected(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 你好\n这是一行无归属文本\nB: 好\n", encoding="utf-8")
    with pytest.raises(InputError) as error:
        parse_chat(path)
    assert "第 2 行" in str(error.value)


def test_empty_body_rejected(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A:\nB: 好\n", encoding="utf-8")
    with pytest.raises(InputError):
        parse_chat(path)


def test_both_speakers_required(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 只有我\nA: 还是我\n", encoding="utf-8")
    with pytest.raises(InputError):
        parse_chat(path)


def test_empty_file_rejected(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("   \n\n", encoding="utf-8")
    with pytest.raises(InputError):
        parse_chat(path)


def test_nul_rejected(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_bytes(b"A: hi\x00\nB: ok\n")
    with pytest.raises(InputError):
        parse_chat(path)


def test_directory_rejected(tmp_path):
    with pytest.raises(InputError):
        parse_chat(tmp_path)


def test_invalid_utf8_rejected(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_bytes(b"A: \xff\xfe\nB: ok\n")
    with pytest.raises(InputError):
        parse_chat(path)
