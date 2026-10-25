"""Code-assembled Persona with full observation audit."""

from __future__ import annotations

from typing import Any

from person_simulator.errors import EvidenceError
from person_simulator.models import (
    Coverage,
    DialogueExample,
    Dimension,
    ExampleCandidate,
    ExampleLine,
    Feature,
    Message,
    Observation,
    Persona,
    SelectionAudit,
)


def _contiguous(candidate: ExampleCandidate, message_index: dict[str, int], messages: dict[str, Message]) -> bool:
    if not candidate.message_ids:
        return False
    try:
        positions = [message_index[message_id] for message_id in candidate.message_ids]
    except KeyError:
        return False
    return positions == list(range(positions[0], positions[0] + len(positions)))


CATEGORY_PRIORITY = ["日常交流", "亲近/感谢", "冲突/不满", "拒绝/边界", "修复/道歉"]
FEATURE_LIMITS: dict[Dimension, int] = {
    Dimension.LANGUAGE: 10,
    Dimension.BEHAVIOR: 10,
    Dimension.THINKING: 8,
    Dimension.EMOTION: 8,
    Dimension.RELATIONSHIP: 8,
    Dimension.HISTORY: 8,
    Dimension.CHANGES: 6,
    Dimension.UNCERTAINTY: 6,
}
CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("修复/道歉", ("对不起", "抱歉", "我错了", "别生气", "原谅")),
    ("冲突/不满", ("生气", "吵", "烦", "过分", "不理", "失望")),
    ("拒绝/边界", ("不行", "不想", "不要", "没空", "算了", "不方便", "拒绝")),
    ("亲近/感谢", ("谢谢", "喜欢你", "想你", "陪你", "开心", "辛苦")),
]


def _situation_category(selected: list[Message]) -> str:
    text = " ".join(message.text for message in selected)
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category
    return "日常交流"


def build_examples(
    candidates: list[ExampleCandidate],
    *,
    messages: dict[str, Message],
    message_order: list[str],
    target: str,
) -> tuple[list[DialogueExample], list[str]]:
    index = {message_id: position for position, message_id in enumerate(message_order)}
    gathered: list[tuple[str, DialogueExample]] = []
    skipped: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        key = tuple(candidate.message_ids)
        if key in seen:
            continue
        seen.add(key)
        if len(candidate.message_ids) < 2 or len(candidate.message_ids) > 8:
            skipped.append("示例候选不是 2—8 条消息")
            continue
        if not _contiguous(candidate, index, messages):
            skipped.append("示例候选不是连续原始片段")
            continue
        selected = [messages[message_id] for message_id in candidate.message_ids]
        if not any(message.speaker == target for message in selected):
            skipped.append("示例候选没有目标人物发言")
            continue
        category = _situation_category(selected)
        gathered.append(
            (
                category,
                DialogueExample(
                    id=f"ex{len(gathered) + 1:03d}",
                    message_ids=candidate.message_ids,
                    lines=[
                        ExampleLine(
                            speaker=message.speaker,
                            text=message.text,
                            timestamp=message.timestamp,
                        )
                        for message in selected
                    ],
                    situation=(
                        f"消息顺序上的连续片段（{selected[0].id}–{selected[-1].id}）；"
                        f"按关键词标注：{category}"
                    ),
                ),
            )
        )

    by_category: dict[str, list[tuple[str, DialogueExample]]] = {}
    for category, example in gathered:
        by_category.setdefault(category, []).append((category, example))

    chosen: list[DialogueExample] = []
    for category in CATEGORY_PRIORITY:
        pool = by_category.get(category, [])
        if pool:
            chosen.append(pool.pop(0)[1])
    for category in CATEGORY_PRIORITY:
        for _, example in by_category.get(category, []):
            if len(chosen) >= 12:
                break
            chosen.append(example)
        if len(chosen) >= 12:
            break
    if len(gathered) > 12:
        skipped.append("示例候选超过 12 段，按情境覆盖取舍，完整候选未进入导出")

    chosen.sort(key=lambda example: index[example.message_ids[0]])
    for number, example in enumerate(chosen, start=1):
        example.id = f"ex{number:03d}"
    return chosen, skipped


def assemble_persona(
    *,
    target: str,
    interlocutor: str,
    source_hash: str,
    coverage: Coverage,
    features_by_dimension: dict[Dimension, list[Feature]],
    observations: list[Observation],
    examples: list[DialogueExample],
    unknowns: list[str],
) -> Persona:
    observation_by_id = {observation.id: observation for observation in observations}
    selected_by_dimension: dict[Dimension, list[Feature]] = {}
    dropped_observations: set[str] = set()
    all_feature_observations: set[str] = set()
    for dimension, features in features_by_dimension.items():
        for feature in features:
            if feature.dimension != dimension:
                raise EvidenceError(
                    "feature 维度与所在分组不一致",
                    stage="persona",
                )
            all_feature_observations.update(feature.observation_ids)
        ranked = sorted(
            features,
            key=lambda item: (
                CONFIDENCE_RANK.get(item.confidence.value, 3),
                -len(item.evidence_refs),
                item.id,
            ),
        )
        limit = FEATURE_LIMITS.get(dimension, 8)
        selected_by_dimension[dimension] = ranked[:limit]
        for feature in ranked[limit:]:
            dropped_observations.update(feature.observation_ids)

    used: set[str] = set()
    for dimension, features in selected_by_dimension.items():
        for feature in features:
            for observation_id in feature.observation_ids:
                if observation_id not in observation_by_id:
                    raise EvidenceError(
                        "feature 追溯了不存在的 observation",
                        stage="persona",
                    )
                used.add(observation_id)

    audit = [
        SelectionAudit(
            observation_id=observation.id,
            included=observation.id in used,
            reason=(
                "进入最终人物特征"
                if observation.id in used
                else (
                    "超出每维展示上限；原始观察仍保留在 evidence.jsonl"
                    if observation.id in dropped_observations
                    else "未形成稳定特征，未进入最终导出提示词"
                )
            ),
        )
        for observation in sorted(observations, key=lambda item: item.id)
    ]

    clean_unknowns: list[str] = []
    for item in unknowns:
        if item not in clean_unknowns:
            clean_unknowns.append(item)

    return Persona(
        target=target,
        interlocutor=interlocutor,
        source_hash=source_hash,
        coverage=coverage,
        language=selected_by_dimension.get(Dimension.LANGUAGE, []),
        behavior=selected_by_dimension.get(Dimension.BEHAVIOR, []),
        thinking=selected_by_dimension.get(Dimension.THINKING, []),
        emotion=selected_by_dimension.get(Dimension.EMOTION, []),
        relationship=selected_by_dimension.get(Dimension.RELATIONSHIP, []),
        history=selected_by_dimension.get(Dimension.HISTORY, []),
        changes=selected_by_dimension.get(Dimension.CHANGES, []),
        uncertainty=selected_by_dimension.get(Dimension.UNCERTAINTY, []),
        examples=examples,
        unknowns=clean_unknowns,
        selection_audit=audit,
    )


def persona_stats(persona: Persona) -> dict[str, Any]:
    dimensions = {
        "language": persona.language,
        "behavior": persona.behavior,
        "thinking": persona.thinking,
        "emotion": persona.emotion,
        "relationship": persona.relationship,
        "history": persona.history,
        "changes": persona.changes,
        "uncertainty": persona.uncertainty,
    }
    return {
        "features": {name: len(items) for name, items in dimensions.items()},
        "empty_dimensions": [name for name, items in dimensions.items() if not items],
        "examples": len(persona.examples),
        "observations_in_audit": len(persona.selection_audit),
        "observations_included": sum(1 for entry in persona.selection_audit if entry.included),
        "conflicts": sum(1 for entry in persona.selection_audit if not entry.included),
    }
