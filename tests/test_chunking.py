from __future__ import annotations

import pytest

from person_simulator.budget import estimate_tokens
from person_simulator.chunking import build_chunk_plan
from person_simulator.errors import ConfigError
from person_simulator.parser import parse_chat


def _chat(tmp_path, text: str):
    path = tmp_path / "chat.txt"
    path.write_text(text, encoding="utf-8")
    return parse_chat(path)


def _reassemble(messages, parts):
    by_message: dict[str, list] = {}
    part_by_id = {part.id: part for part in parts}
    result = {}
    for message in messages:
        result[message.id] = ""
    for part in parts:
        by_message.setdefault(part.message_id, []).append(part)
    for message in messages:
        selected = sorted(by_message[message.id], key=lambda part: part.start)
        result[message.id] = "".join(part_by_id[part.id].text for part in selected)
    return result


def test_every_character_assigned_once_and_reassembled(tmp_path):
    text = "".join(f"A: 消息{i}🙂\nB: 回复{i}\n" for i in range(20))
    parsed = _chat(tmp_path, text)
    plan = build_chunk_plan(parsed, "A", chunk_input_budget=700, overlap_messages=2)
    assert plan.coverage.complete
    assert plan.coverage.ratio == 1.0
    core_ids = [part_id for chunk in plan.chunks for part_id in chunk.core_parts]
    assert sorted(core_ids) == sorted(part.id for part in plan.parts)
    rebuilt = _reassemble(parsed.messages, plan.parts)
    assert all(rebuilt[message.id] == message.text for message in parsed.messages)


def test_deterministic_chunk_ids(tmp_path):
    parsed = _chat(tmp_path, "A: 一\nB: 二\nA: 三\nB: 四\n")
    first = build_chunk_plan(parsed, "A", chunk_input_budget=600, overlap_messages=1)
    second = build_chunk_plan(parsed, "A", chunk_input_budget=600, overlap_messages=1)
    assert [chunk.id for chunk in first.chunks] == [chunk.id for chunk in second.chunks]
    assert [part.id for part in first.parts] == [part.id for part in second.parts]


def test_long_message_split_without_loss(tmp_path):
    long_text = ("这是一段很长的文字。" * 500) + "END🙂"
    parsed = _chat(tmp_path, f"A: {long_text}\nB: 收到\n")
    plan = build_chunk_plan(parsed, "A", chunk_input_budget=600, overlap_messages=1)
    target_parts = [part for part in plan.parts if part.message_id == "m000001"]
    assert len(target_parts) > 1
    assert "".join(part.text for part in target_parts) == long_text
    assert plan.coverage.complete


def test_chunks_respect_budget_and_context_limit(tmp_path):
    text = "".join(f"A: 第{i}条内容内容内容\nB: 回复{i}\n" for i in range(30))
    parsed = _chat(tmp_path, text)
    plan = build_chunk_plan(parsed, "A", chunk_input_budget=650, overlap_messages=4)
    assert len(plan.chunks) > 1
    part_by_id = {part.id: part for part in plan.parts}
    message_count = {message.id: 0 for message in parsed.messages}
    for chunk in plan.chunks:
        assert chunk.budget_estimate <= 650
        assert len({part_by_id[pid].message_id for pid in chunk.context_parts}) <= 4
        assert not (set(chunk.core_parts) & set(chunk.context_parts))
        for pid in chunk.context_parts:
            message_count[part_by_id[pid].message_id] += 1
        for pid in chunk.core_parts:
            message_count[part_by_id[pid].message_id] += 1
    assert all(count >= 1 for count in message_count.values())


def test_sessions_are_preferred_boundaries(tmp_path):
    text = (
        "[2024-01-01T10:00:00+08:00] A: 一\n"
        "[2024-01-01T10:01:00+08:00] B: 二\n"
        "[2024-01-01T12:00:00+08:00] A: 三\n"
        "[2024-01-01T12:01:00+08:00] B: 四\n"
    )
    parsed = _chat(tmp_path, text)
    plan = build_chunk_plan(parsed, "A", chunk_input_budget=600, overlap_messages=2)
    assert plan.coverage.complete
    assert len(plan.chunks) >= 1
    part_message = {part.id: part.message_id for part in plan.parts}
    message_session = {message.id: message.session_id for message in parsed.messages}
    assert len({message_session[part_message[pid]] for pid in plan.chunks[0].core_parts}) >= 1


def test_too_small_budget_rejected(tmp_path):
    parsed = _chat(tmp_path, "A: 一\nB: 二\n")
    with pytest.raises(ConfigError):
        build_chunk_plan(parsed, "A", chunk_input_budget=500, overlap_messages=1)


def test_coverage_only_counts_core(tmp_path):
    parsed = _chat(tmp_path, "A: 一\nB: 二\nA: 三\nB: 四\n")
    plan = build_chunk_plan(parsed, "B", chunk_input_budget=600, overlap_messages=4)
    assert plan.coverage.target_messages == 2
    assert plan.coverage.covered_chars > 0
    assert plan.coverage.covered_chars == plan.coverage.total_chars
