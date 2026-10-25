"""JSON parsing and evidence validation.

Structural validation proves traceability, never semantic correctness.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import ValidationError

from person_simulator.errors import EvidenceError, ResponseFormatError
from person_simulator.models import (
    Chunk,
    Dimension,
    EvidenceRef,
    Feature,
    Message,
    MessagePart,
    Observation,
    ObservationKind,
    ReduceOutput,
    SegmentAnalysis,
)

FENCE_RE = re.compile(r"^```(?:json)?[ \t]*\r?\n(?P<body>.*)\r?\n```$", re.DOTALL)


@dataclass(frozen=True)
class ResolvedRef:
    message_id: str
    start: int
    end: int
    speaker: str
    quote: str

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.message_id, self.start, self.end)


@dataclass
class VerifiedSegment:
    analysis: SegmentAnalysis
    evidence: list[dict[str, Any]]


def parse_json_object(content: str, *, task_id: str | None = None) -> dict[str, Any]:
    text = content.strip()
    if not text:
        raise ResponseFormatError("模型返回空内容", stage="modeling", task_id=task_id)
    if text.startswith("```"):
        match = FENCE_RE.match(text)
        if not match:
            raise ResponseFormatError(
                "代码围栏没有包裹整个响应",
                stage="modeling",
                task_id=task_id,
                hint="只允许一个完整 JSON 代码围栏或裸 JSON 对象",
            )
        text = match.group("body").strip()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ResponseFormatError(
            "模型响应不是合法 JSON",
            stage="modeling",
            task_id=task_id,
            hint="要求模型只返回完整 JSON 对象",
        ) from exc
    if not isinstance(data, dict):
        raise ResponseFormatError(
            "模型响应 JSON 顶层不是对象",
            stage="modeling",
            task_id=task_id,
        )
    return data


def resolve_ref(
    ref: EvidenceRef,
    messages: dict[str, Message],
    *,
    allowed_message_ids: set[str] | None = None,
    task_id: str | None = None,
) -> ResolvedRef:
    message = messages.get(ref.message_id)
    if message is None:
        raise EvidenceError(
            "证据引用了不存在的消息 ID",
            stage="modeling",
            task_id=task_id,
        )
    if allowed_message_ids is not None and ref.message_id not in allowed_message_ids:
        raise EvidenceError(
            "证据引用了当前任务不允许访问的消息",
            stage="modeling",
            task_id=task_id,
        )
    if ref.start < 0 or ref.end > len(message.text) or ref.end <= ref.start:
        raise EvidenceError(
            "证据字符偏移越界",
            stage="modeling",
            task_id=task_id,
            hint=f"消息 {ref.message_id} 的合法范围是 0..{len(message.text)}",
        )
    quote = message.text[ref.start : ref.end]
    if not quote.strip():
        raise EvidenceError(
            "证据切片为空或只有空白",
            stage="modeling",
            task_id=task_id,
        )
    return ResolvedRef(
        message_id=ref.message_id,
        start=ref.start,
        end=ref.end,
        speaker=message.speaker,
        quote=quote,
    )


def _overlaps_core(ref: EvidenceRef, core_parts: Iterable[MessagePart]) -> bool:
    for part in core_parts:
        if part.message_id == ref.message_id and ref.start < part.end and ref.end > part.start:
            return True
    return False


def validate_segment(
    analysis: SegmentAnalysis,
    *,
    chunk: Chunk,
    messages: dict[str, Message],
    parts: dict[str, MessagePart],
    target: str,
    interlocutor: str,
) -> VerifiedSegment:
    task_id = f"extract:{chunk.id}"
    if analysis.chunk_id != chunk.id:
        raise EvidenceError("SegmentAnalysis.chunk_id 与任务不一致", stage="modeling", task_id=task_id)
    if analysis.target != target:
        raise EvidenceError("SegmentAnalysis.target 与任务不一致", stage="modeling", task_id=task_id)

    if len(set(analysis.processed_core_part_ids)) != len(analysis.processed_core_part_ids):
        raise EvidenceError("processed_core_part_ids 有重复", stage="modeling", task_id=task_id)
    if set(analysis.processed_core_part_ids) != set(chunk.core_parts):
        raise EvidenceError(
            "processed_core_part_ids 没有精确覆盖当前块的 core parts",
            stage="modeling",
            task_id=task_id,
        )

    core_parts = [parts[part_id] for part_id in chunk.core_parts]
    allowed_messages = {
        parts[part_id].message_id for part_id in chunk.core_parts + chunk.context_parts
    }
    notes = {note.part_id: note.reason for note in analysis.processed_no_observation}
    if len(notes) != len(analysis.processed_no_observation):
        raise EvidenceError("processed_no_observation 有重复 part", stage="modeling", task_id=task_id)
    unknown_notes = set(notes) - set(chunk.core_parts)
    if unknown_notes:
        raise EvidenceError(
            "processed_no_observation 包含非 core part",
            stage="modeling",
            task_id=task_id,
        )

    observation_ids: set[str] = set()
    covered_parts: set[str] = set()
    evidence_records: list[dict[str, Any]] = []

    for observation in analysis.observations:
        if observation.id in observation_ids:
            raise EvidenceError("observation ID 重复", stage="modeling", task_id=task_id)
        observation_ids.add(observation.id)
        if observation.dimension not in set(Dimension):
            raise EvidenceError("observation 维度非法", stage="modeling", task_id=task_id)

        resolved_support: list[ResolvedRef] = []
        for ref in observation.evidence_refs:
            resolved = resolve_ref(
                ref,
                messages,
                allowed_message_ids=allowed_messages,
                task_id=task_id,
            )
            resolved_support.append(resolved)
            evidence_records.append(
                {
                    "observation_id": observation.id,
                    "role": "support",
                    "message_id": resolved.message_id,
                    "start": resolved.start,
                    "end": resolved.end,
                    "speaker": resolved.speaker,
                    "quote": resolved.quote,
                }
            )
            for part in core_parts:
                if (
                    part.message_id == resolved.message_id
                    and resolved.start < part.end
                    and resolved.end > part.start
                ):
                    covered_parts.add(part.id)

        target_core_support = any(
            resolved.speaker == target
            and _overlaps_core(EvidenceRef(message_id=resolved.message_id, start=resolved.start, end=resolved.end), core_parts)
            for resolved in resolved_support
        )
        if not target_core_support:
            raise EvidenceError(
                "observation 缺少目标人物在当前 core 中的发言证据",
                stage="modeling",
                task_id=task_id,
                hint="对方发言不能单独支撑目标人格特征",
            )

        if observation.kind == ObservationKind.REPORTED_FACT:
            speakers = {resolved.speaker for resolved in resolved_support}
            if not observation.source_speaker:
                if len(speakers) == 1:
                    observation.source_speaker = next(iter(speakers))
                else:
                    raise EvidenceError(
                        "reported_fact 缺少 source_speaker，且证据来自多位说话人",
                        stage="modeling",
                        task_id=task_id,
                    )
            if observation.source_speaker not in speakers:
                if len(speakers) == 1:
                    observation.source_speaker = next(iter(speakers))
                else:
                    raise EvidenceError(
                        "reported_fact 的 source_speaker 没有对应证据",
                        stage="modeling",
                        task_id=task_id,
                    )

        for ref in observation.counter_evidence_refs:
            resolved = resolve_ref(
                ref,
                messages,
                allowed_message_ids=allowed_messages,
                task_id=task_id,
            )
            evidence_records.append(
                {
                    "observation_id": observation.id,
                    "role": "counter",
                    "message_id": resolved.message_id,
                    "start": resolved.start,
                    "end": resolved.end,
                    "speaker": resolved.speaker,
                    "quote": resolved.quote,
                }
            )

    for part in core_parts:
        has_observation = part.id in covered_parts
        has_note = part.id in notes
        if has_observation and has_note:
            raise EvidenceError(
                "part 同时被观察覆盖并声明无观察",
                stage="modeling",
                task_id=task_id,
            )
        if not has_observation and not has_note:
            raise EvidenceError(
                "core part 没有处理去向",
                stage="modeling",
                task_id=task_id,
                hint=f"part {part.id} 需要观察证据或 processed_no_observation",
            )

    core_message_order: list[str] = []
    for part in core_parts:
        if part.message_id not in core_message_order:
            core_message_order.append(part.message_id)
    for candidate in analysis.example_candidates:
        if len(candidate.message_ids) > 8:
            raise EvidenceError("示例候选超过 8 条消息", stage="modeling", task_id=task_id)
        if not set(candidate.message_ids) <= set(core_message_order):
            raise EvidenceError("示例候选引用了非 core 消息", stage="modeling", task_id=task_id)
        positions = [core_message_order.index(mid) for mid in candidate.message_ids]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise EvidenceError(
                "示例候选不是连续原始片段",
                stage="modeling",
                task_id=task_id,
            )

    return VerifiedSegment(analysis=analysis, evidence=evidence_records)


def parse_segment_analysis(payload: dict[str, Any], *, task_id: str) -> SegmentAnalysis:
    try:
        return SegmentAnalysis.model_validate(payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.get('loc', []))}:{error.get('msg', '')[:60]}"
            for error in exc.errors(include_url=False)[:6]
        )
        raise ResponseFormatError(
            f"SegmentAnalysis 结构校验失败：{exc.error_count()} 个字段（{details}）",
            stage="modeling",
            task_id=task_id,
            hint="按契约字段重新输出完整 JSON",
        ) from exc


def parse_reduce_output(payload: dict[str, Any], *, task_id: str) -> ReduceOutput:
    try:
        return ReduceOutput.model_validate(payload)
    except ValidationError as exc:
        raise ResponseFormatError(
            f"ReduceOutput 结构校验失败：{exc.error_count()} 个字段",
            stage="modeling",
            task_id=task_id,
        ) from exc


def _item_source_ids(item: dict[str, Any]) -> set[str]:
    if isinstance(item.get("observation_ids"), list):
        return {str(value) for value in item["observation_ids"]}
    return {str(item.get("id"))}


def _item_ref_keys(item: dict[str, Any]) -> set[tuple[str, int, int]]:
    keys: set[tuple[str, int, int]] = set()
    for ref in item.get("evidence_refs", []):
        if isinstance(ref, dict):
            keys.add((str(ref.get("message_id")), int(ref.get("start", 0)), int(ref.get("end", 0))))
    return keys


def validate_reduce_output(
    output: ReduceOutput,
    *,
    items: list[dict[str, Any]],
    messages: dict[str, Message],
    target: str,
    dimension: Dimension,
    task_id: str,
) -> None:
    if output.dimension != dimension:
        raise EvidenceError("汇总维度与任务不一致", stage="modeling", task_id=task_id)
    if output.target != target:
        raise EvidenceError("汇总 target 与任务不一致", stage="modeling", task_id=task_id)

    item_ids = [str(item.get("id")) for item in items]
    if len(set(item_ids)) != len(item_ids):
        raise EvidenceError("汇总输入 item ID 重复", stage="modeling", task_id=task_id)
    disposition_ids = [entry.item_id for entry in output.dispositions]
    if len(set(disposition_ids)) != len(disposition_ids):
        raise EvidenceError("disposition 重复", stage="modeling", task_id=task_id)
    if set(disposition_ids) != set(item_ids):
        raise EvidenceError(
            "disposition 没有恰好覆盖全部输入观察",
            stage="modeling",
            task_id=task_id,
        )

    feature_ids = [feature.id for feature in output.features]
    if len(set(feature_ids)) != len(feature_ids):
        raise EvidenceError("feature ID 重复", stage="modeling", task_id=task_id)
    feature_by_id = {feature.id: feature for feature in output.features}

    source_obs: dict[str, set[str]] = {
        str(item.get("id")): _item_source_ids(item) for item in items
    }
    all_obs = set().union(*source_obs.values()) if source_obs else set()
    refs_by_item = {str(item.get("id")): _item_ref_keys(item) for item in items}

    for entry in output.dispositions:
        if entry.disposition == "merged":
            if not entry.feature_id or entry.feature_id not in feature_by_id:
                raise EvidenceError(
                    "merged disposition 缺少有效 feature_id",
                    stage="modeling",
                    task_id=task_id,
                )

    for feature in output.features:
        if feature.dimension != dimension:
            raise EvidenceError("feature 维度与任务不一致", stage="modeling", task_id=task_id)
        if not set(feature.observation_ids) <= all_obs:
            raise EvidenceError(
                "feature 引用了不属于输入的 observation",
                stage="modeling",
                task_id=task_id,
            )
        allowed_refs: set[tuple[str, int, int]] = set()
        for item_id, obs_ids in source_obs.items():
            if obs_ids & set(feature.observation_ids):
                allowed_refs |= refs_by_item[item_id]
        for ref in feature.evidence_refs:
            resolved = resolve_ref(ref, messages, task_id=task_id)
            if resolved.key not in allowed_refs:
                raise EvidenceError(
                    "feature 增加了输入中不存在的证据",
                    stage="modeling",
                    task_id=task_id,
                )
        if not any(
            resolve_ref(ref, messages, task_id=task_id).speaker == target
            for ref in feature.evidence_refs
        ):
            raise EvidenceError(
                "feature 缺少目标人物证据",
                stage="modeling",
                task_id=task_id,
            )
        for ref in feature.counter_observation_ids:
            if ref not in all_obs:
                raise EvidenceError(
                    "counter_observation_ids 引用了未知观察",
                    stage="modeling",
                    task_id=task_id,
                )


def collect_observations(analyses: Iterable[SegmentAnalysis]) -> list[Observation]:
    result: list[Observation] = []
    for analysis in analyses:
        result.extend(analysis.observations)
    return result


def feature_payload(feature: Feature) -> dict[str, Any]:
    return feature.model_dump(mode="json")


def observation_payload(observation: Observation) -> dict[str, Any]:
    return observation.model_dump(mode="json")
