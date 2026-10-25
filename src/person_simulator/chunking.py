"""Budget-bounded chunking with exact Unicode coverage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from person_simulator.budget import PACKAGING_MARGIN, estimate_tokens
from person_simulator.errors import ConfigError, InputError
from person_simulator.models import Chunk, Coverage, Message, MessagePart, SourceRange
from person_simulator.parser import ParsedChat

BREAK_CHARS = "\n。！？!?；;，,、 "


@dataclass
class ChunkPlan:
    parts: list[MessagePart]
    chunks: list[Chunk]
    coverage: Coverage
    speaker_a: str
    speaker_b: str

    @property
    def map_call_lower_bound(self) -> int:
        return len(self.chunks)


def _split_text(text: str, max_tokens: int) -> list[str]:
    if estimate_tokens(text) <= max_tokens:
        return [text]
    pieces: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        low, high = start + 1, length
        while low < high:
            mid = (low + high + 1) // 2
            if estimate_tokens(text[start:mid]) <= max_tokens:
                low = mid
            else:
                high = mid - 1
        end = low
        if end < length:
            floor = start + max(1, (end - start) // 2)
            for pos in range(end - 1, floor - 1, -1):
                if text[pos] in BREAK_CHARS:
                    end = pos + 1
                    break
        if end <= start:
            end = start + 1
        pieces.append(text[start:end])
        start = end
    return pieces


def build_parts(messages: list[Message], chunk_input_budget: int) -> list[MessagePart]:
    max_content = chunk_input_budget - PACKAGING_MARGIN
    if max_content < 64:
        raise ConfigError(
            "chunk_input_budget 太小，扣除包装余量后不足 64",
            stage="chunking",
            hint="将 chunking.chunk_input_budget 提高到至少 576",
        )
    parts: list[MessagePart] = []
    for message in messages:
        pieces = _split_text(message.text, max_content)
        cursor = 0
        for number, piece in enumerate(pieces, start=1):
            offset = cursor
            cursor += len(piece)
            if message.text[offset:cursor] != piece:  # pragma: no cover - defensive
                raise InputError("切分片段无法回源", stage="chunking")
            parts.append(
                MessagePart(
                    id=f"{message.id}:p{number}",
                    message_id=message.id,
                    start=offset,
                    end=cursor,
                    text=piece,
                )
            )
    return parts


def _verify_partition(messages: list[Message], parts: list[MessagePart]) -> None:
    by_message: dict[str, list[MessagePart]] = {}
    for part in parts:
        by_message.setdefault(part.message_id, []).append(part)
    for message in messages:
        message_parts = sorted(by_message.get(message.id, []), key=lambda p: p.start)
        cursor = 0
        rebuilt: list[str] = []
        for part in message_parts:
            if part.start != cursor:
                raise InputError(
                    "切分区间不连续",
                    stage="chunking",
                    hint=f"检查消息 {message.id} 的片段边界",
                )
            if part.text != message.text[part.start : part.end]:
                raise InputError(
                    "切分文本与原文不一致",
                    stage="chunking",
                    hint=f"检查消息 {message.id} 的片段内容",
                )
            rebuilt.append(part.text)
            cursor = part.end
        if cursor != len(message.text) or "".join(rebuilt) != message.text:
            raise InputError(
                "切分未完整覆盖消息",
                stage="chunking",
                hint=f"检查消息 {message.id} 的尾部",
            )


def build_chunk_plan(
    parsed: ParsedChat,
    target: str,
    *,
    chunk_input_budget: int = 6000,
    overlap_messages: int = 4,
) -> ChunkPlan:
    if target not in (parsed.speaker_a, parsed.speaker_b):
        raise InputError("target 不属于两位说话人", stage="chunking")
    if overlap_messages < 0:
        raise ConfigError("overlap_messages 不能为负数", stage="chunking")

    messages = parsed.messages
    parts = build_parts(messages, chunk_input_budget)
    _verify_partition(messages, parts)

    message_by_id = {m.id: m for m in messages}
    parts_by_message: dict[str, list[MessagePart]] = {}
    for part in parts:
        parts_by_message.setdefault(part.message_id, []).append(part)
    part_by_id = {p.id: p for p in parts}
    message_index = {m.id: m.index for m in messages}

    def estimate_parts(ids: list[str]) -> int:
        return PACKAGING_MARGIN + sum(estimate_tokens(part_by_id[i].text) for i in ids)

    def context_for(core_ids: list[str], core_estimate: int) -> list[str]:
        first_message = message_by_id[part_by_id[core_ids[0]].message_id]
        first_index = first_message.index
        core_message_ids = {part_by_id[i].message_id for i in core_ids}
        candidates = [
            message
            for message in messages[max(0, first_index - overlap_messages) : first_index]
            if message.session_id == first_message.session_id
        ]
        selected: list[str] = []
        used = core_estimate
        for message in reversed(candidates):
            if message.id in core_message_ids:
                continue
            ids = [p.id for p in parts_by_message[message.id]]
            cost = sum(estimate_tokens(part_by_id[i].text) for i in ids)
            if used + cost <= chunk_input_budget:
                selected.insert(0, message.id)
                used += cost
        result: list[str] = []
        for message_id in selected:
            result.extend(p.id for p in parts_by_message[message_id])
        return result

    raw_chunks: list[dict[str, object]] = []
    core: list[str] = []
    context: list[str] = []
    current_session: str | None = None

    for part in parts:
        session_id = message_by_id[part.message_id].session_id
        if not core:
            core = [part.id]
            context = context_for(core, estimate_parts(core))
            current_session = session_id
            continue

        if session_id != current_session and estimate_parts(core) >= chunk_input_budget * 0.5:
            raw_chunks.append({"core": list(core), "context": list(context)})
            core = [part.id]
            context = context_for(core, estimate_parts(core))
            current_session = session_id
            continue

        # Small sessions may be merged to keep request count and cost bounded.
        current_session = session_id

        trial_core = core + [part.id]
        trial_estimate = estimate_parts(trial_core)
        trial_context = context_for(trial_core, trial_estimate)
        if trial_estimate > chunk_input_budget:
            raw_chunks.append({"core": list(core), "context": list(context)})
            core = [part.id]
            context = context_for(core, estimate_parts(core))
            current_session = session_id
        elif trial_estimate + sum(
            estimate_tokens(part_by_id[i].text) for i in trial_context
        ) - PACKAGING_MARGIN <= chunk_input_budget:
            core = trial_core
            context = trial_context
        else:
            raw_chunks.append({"core": list(core), "context": list(context)})
            core = [part.id]
            context = context_for(core, estimate_parts(core))
            current_session = session_id

    if core:
        raw_chunks.append({"core": list(core), "context": list(context)})

    chunks: list[Chunk] = []
    for number, raw in enumerate(raw_chunks, start=1):
        core_ids = list(raw["core"])  # type: ignore[arg-type]
        context_ids = list(raw["context"])  # type: ignore[arg-type]
        core_messages = [part_by_id[i].message_id for i in core_ids]
        first = message_by_id[core_messages[0]]
        last = message_by_id[core_messages[-1]]
        digest = hashlib.sha256(
            (
                f"{parsed.source_hash}|{target}|{chunk_input_budget}|{overlap_messages}|"
                + ",".join(core_ids)
                + "|"
                + ",".join(context_ids)
            ).encode("utf-8")
        ).hexdigest()[:12]
        budget = estimate_parts(core_ids) + sum(
            estimate_tokens(part_by_id[i].text) for i in context_ids
        )
        chunks.append(
            Chunk(
                id=f"c{number:04d}-{digest}",
                core_parts=core_ids,
                context_parts=context_ids,
                source_range=SourceRange(
                    first_message_id=first.id,
                    last_message_id=last.id,
                    line_start=first.line_start,
                    line_end=last.line_end,
                ),
                budget_estimate=budget,
            )
        )

    core_seen: list[str] = []
    for chunk in chunks:
        core_seen.extend(chunk.core_parts)
    if sorted(core_seen) != sorted(p.id for p in parts):
        raise InputError(
            "core 片段没有恰好各归属一次",
            stage="chunking",
            hint="检查切分计划",
        )

    target_messages = [m for m in messages if m.speaker == target]
    total_chars = sum(len(m.text) for m in target_messages)
    core_part_ids = [p.id for p in parts if message_by_id[p.message_id].speaker == target]
    covered = sum(len(part_by_id[i].text) for i in core_part_ids)
    ratio = (covered / total_chars) if total_chars else 1.0

    coverage = Coverage(
        source_hash=parsed.source_hash,
        total_messages=len(messages),
        target_messages=len(target_messages),
        total_chars=total_chars,
        covered_chars=covered,
        ratio=ratio,
        complete=(covered == total_chars),
        core_part_ids=core_part_ids,
    )

    return ChunkPlan(
        parts=parts,
        chunks=chunks,
        coverage=coverage,
        speaker_a=parsed.speaker_a,
        speaker_b=parsed.speaker_b,
    )
