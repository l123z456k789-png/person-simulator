"""Deterministic offline mock client.

The mock never performs network access. It derives shallow, traceable
observations from the synthetic text it is given; it is not a real model
and its output is always marked as a synthetic demonstration.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from person_simulator.errors import (
    AuthenticationError,
    ContextLimitError,
    OutputTruncatedError,
    ProviderUnavailable,
    RateLimitError,
    TransportError,
)
from person_simulator.providers.base import ModelRequest, ModelResponse

SENTENCE_ENDS = "。！？!?；;\n"


def _first_sentence(text: str, limit: int = 80) -> str:
    for index, char in enumerate(text):
        if char in SENTENCE_ENDS:
            return text[: index + 1][:limit]
    return text[:limit]


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int, int]] = set()
    result: list[dict[str, Any]] = []
    for ref in refs:
        key = (ref["message_id"], ref["start"], ref["end"])
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


class MockClient:
    provider = "mock"
    is_mock = True

    def __init__(self, faults: dict[str, str] | None = None) -> None:
        self.faults = faults or {}
        self.calls: list[str] = []

    def _fault(self, task_id: str) -> str | None:
        return self.faults.get(task_id) or self.faults.get("*")

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request.task_id)
        fault = self._fault(request.task_id)
        if fault in {"timeout", "transport"}:
            raise TransportError(
                "Mock 注入的传输失败",
                stage="provider",
                task_id=request.task_id,
            )
        if fault in {"429", "rate_limit"}:
            error = RateLimitError(
                "Mock 注入的限流",
                stage="provider",
                task_id=request.task_id,
            )
            error.retry_after = 0.0  # type: ignore[attr-defined]
            raise error
        if fault in {"503", "unavailable"}:
            raise ProviderUnavailable(
                "Mock 注入的服务不可用",
                stage="provider",
                task_id=request.task_id,
            )
        if fault in {"auth", "401"}:
            raise AuthenticationError(
                "Mock 注入的鉴权失败",
                stage="provider",
                task_id=request.task_id,
            )
        if fault in {"truncated", "length"}:
            raise OutputTruncatedError(
                "Mock 注入的输出截断",
                stage="provider",
                task_id=request.task_id,
            )
        if fault in {"context", "context_limit"}:
            raise ContextLimitError(
                "Mock 注入的上下文超限",
                stage="provider",
                task_id=request.task_id,
            )
        if fault == "empty":
            raise ProviderUnavailable(
                "Mock 注入的空内容",
                stage="provider",
                task_id=request.task_id,
            )

        if request.task_id == "doctor-probe":
            content = '{"ok": true}'
        elif request.task_id.startswith("whole:analysis"):
            content = (
                "<system_prompt>\n"
                "MOCK 合成演示：你现在扮演目标人物。保持简短、自然的口语；"
                "不要输出分析；材料不足时承认不知道。\n"
                "现在直接以目标人物的口吻回复。\n"
                "</system_prompt>\n"
                "<person_simulation>\n"
                "MOCK 合成演示，不代表真实人物建模。\n"
                "</person_simulation>"
            )
        elif request.task_id.startswith("whole:simulate"):
            content = "（MOCK 合成回复，不代表真实人物）"
        else:
            payload = self._payload(request)
            task = payload.get("task")
            if task == "extract":
                content = json.dumps(self._extract(payload), ensure_ascii=False)
            elif task == "reduce":
                content = json.dumps(self._reduce(payload), ensure_ascii=False)
            else:
                content = json.dumps(
                    {"error": "unsupported_mock_task", "task": str(task)},
                    ensure_ascii=False,
                )

        if fault == "bad_json":
            content = "{this is not valid json"
        elif fault == "bad_evidence":
            data = json.loads(content)
            self._corrupt_evidence(data)
            content = json.dumps(data, ensure_ascii=False)
        elif fault == "overflow" and request.task_id != "doctor-probe":
            data = json.loads(content)
            if "overflow" in data:
                data["overflow"] = True
            content = json.dumps(data, ensure_ascii=False)

        return ModelResponse(
            content=content,
            finish_reason="stop",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            request_id=f"mock-{len(self.calls)}",
            provider=self.provider,
            is_mock=True,
        )

    @staticmethod
    def _payload(request: ModelRequest) -> dict[str, Any]:
        if len(request.messages) < 2:
            return {}
        try:
            value = json.loads(request.messages[-1]["content"])
        except (ValueError, KeyError):
            return {}
        return value if isinstance(value, dict) else {}

    def _extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        chunk_id = str(payload.get("chunk_id", "unknown"))
        target = str(payload.get("target", ""))
        interlocutor = str(payload.get("interlocutor", ""))
        core: list[dict[str, Any]] = []
        for item in payload.get("core_parts", []):
            if isinstance(item, dict):
                part = dict(item)
            elif isinstance(item, (list, tuple)) and len(item) >= 5:
                part_id = str(item[0])
                part = {
                    "part_id": part_id,
                    "message_id": part_id.split(":", 1)[0],
                    "speaker": str(item[1]),
                    "start": int(item[2]),
                    "end": int(item[3]),
                    "text": str(item[4]),
                }
            else:
                continue
            core.append(part)
        observations: list[dict[str, Any]] = []
        covered_parts: set[str] = set()
        counter = 0

        for position, part in enumerate(core):
            if part.get("speaker") != target:
                continue
            text = str(part.get("text", ""))
            if not text.strip():
                continue
            part_id = str(part.get("part_id"))
            message_id = str(part.get("message_id"))
            start = int(part.get("start", 0))
            sentence = _first_sentence(text)
            if not sentence.strip():
                continue
            end = start + len(sentence)
            evidence = [{"message_id": message_id, "start": start, "end": end}]
            previous_is_interlocutor = position > 0 and core[position - 1].get("speaker") == interlocutor

            counter += 1
            if "？" in sentence or "?" in sentence:
                claim = "会用提问推进对话"
            elif "！" in sentence or "!" in sentence:
                claim = "语气直接，常带感叹"
            else:
                claim = "以简短陈述回应，句子不长"
            observations.append(
                {
                    "id": f"o:{chunk_id}:{counter}",
                    "dimension": "language",
                    "claim": claim,
                    "kind": "observed_pattern",
                    "evidence_refs": evidence,
                    "counter_evidence_refs": [],
                    "scope": {
                        "interlocutor": interlocutor,
                        "message_start_id": message_id,
                        "message_end_id": message_id,
                        "situation": f"消息 {message_id}",
                        "time_scope": None,
                    },
                    "confidence": "medium",
                    "uncertainty": "Mock 演示：只依据当前片段的表面特征",
                }
            )
            covered_parts.add(part_id)

            counter += 1
            behavior_claim = (
                "对对方发言直接回应，不绕开话题"
                if previous_is_interlocutor
                else "主动发起或延续话题"
            )
            observations.append(
                {
                    "id": f"o:{chunk_id}:{counter}",
                    "dimension": "behavior",
                    "claim": behavior_claim,
                    "kind": "observed_pattern",
                    "evidence_refs": evidence,
                    "counter_evidence_refs": [],
                    "scope": {
                        "interlocutor": interlocutor,
                        "message_start_id": message_id,
                        "message_end_id": message_id,
                        "situation": (
                            "回应对方时" if previous_is_interlocutor else "主动发起或延续话题时"
                        ),
                        "time_scope": None,
                    },
                    "confidence": "low",
                    "uncertainty": "Mock 演示：未覆盖其他情境，不能外推到所有场合",
                }
            )

            if any(word in sentence for word in ("看情况", "再说", "我想", "想了想", "还是")):
                counter += 1
                observations.append(
                    {
                        "id": f"o:{chunk_id}:{counter}",
                        "dimension": "thinking",
                        "claim": "做决定前会先保留判断，视情况再定",
                        "kind": "observed_pattern",
                        "evidence_refs": evidence,
                        "counter_evidence_refs": [],
                        "scope": {
                            "interlocutor": interlocutor,
                            "message_start_id": message_id,
                            "message_end_id": message_id,
                            "situation": "需要做决定时",
                            "time_scope": None,
                        },
                        "confidence": "low",
                        "uncertainty": "Mock 演示：只来自单条消息，不能代表稳定决策方式",
                    }
                )

            if any(word in sentence for word in ("累", "烦", "难过", "生气", "失望", "不开心")):
                counter += 1
                observations.append(
                    {
                        "id": f"o:{chunk_id}:{counter}",
                        "dimension": "emotion",
                        "claim": "会直接说出负面状态，但不长篇解释",
                        "kind": "observed_pattern",
                        "evidence_refs": evidence,
                        "counter_evidence_refs": [],
                        "scope": {
                            "interlocutor": interlocutor,
                            "message_start_id": message_id,
                            "message_end_id": message_id,
                            "situation": "表达疲惫或不满时",
                            "time_scope": None,
                        },
                        "confidence": "low",
                        "uncertainty": "Mock 演示：样本有限，不代表所有情绪场景",
                    }
                )
            elif any(word in sentence for word in ("开心", "高兴", "太好了", "喜欢")):
                counter += 1
                observations.append(
                    {
                        "id": f"o:{chunk_id}:{counter}",
                        "dimension": "emotion",
                        "claim": "开心时会直接表达，不刻意收着",
                        "kind": "observed_pattern",
                        "evidence_refs": evidence,
                        "counter_evidence_refs": [],
                        "scope": {
                            "interlocutor": interlocutor,
                            "message_start_id": message_id,
                            "message_end_id": message_id,
                            "situation": "情绪积极时",
                            "time_scope": None,
                        },
                        "confidence": "low",
                        "uncertainty": "Mock 演示：样本有限",
                    }
                )

            if "谢谢" in sentence:
                counter += 1
                observations.append(
                    {
                        "id": f"o:{chunk_id}:{counter}",
                        "dimension": "relationship",
                        "claim": "会直接表达感谢",
                        "kind": "observed_pattern",
                        "evidence_refs": evidence,
                        "counter_evidence_refs": [],
                        "scope": {
                            "interlocutor": interlocutor,
                            "message_start_id": message_id,
                            "message_end_id": message_id,
                            "situation": "表达感谢时",
                            "time_scope": None,
                        },
                        "confidence": "medium",
                        "uncertainty": "Mock 演示：样本有限",
                    }
                )
            if "对不起" in sentence or "抱歉" in sentence:
                counter += 1
                observations.append(
                    {
                        "id": f"o:{chunk_id}:{counter}",
                        "dimension": "relationship",
                        "claim": "会使用道歉修复互动",
                        "kind": "observed_pattern",
                        "evidence_refs": evidence,
                        "counter_evidence_refs": [],
                        "scope": {
                            "interlocutor": interlocutor,
                            "message_start_id": message_id,
                            "message_end_id": message_id,
                            "situation": "冲突或失误后",
                            "time_scope": None,
                        },
                        "confidence": "low",
                        "uncertainty": "Mock 演示：只出现一次，可能不代表稳定模式",
                    }
                )
            if any(word in sentence for word in ("昨天", "上次", "之前")):
                counter += 1
                observations.append(
                    {
                        "id": f"o:{chunk_id}:{counter}",
                        "dimension": "history",
                        "claim": "会提到过往共同经历",
                        "kind": "observed_pattern",
                        "evidence_refs": evidence,
                        "counter_evidence_refs": [],
                        "scope": {
                            "interlocutor": interlocutor,
                            "message_start_id": message_id,
                            "message_end_id": message_id,
                            "situation": "回忆过去时",
                            "time_scope": "消息顺序上的较早时期",
                        },
                        "confidence": "low",
                        "uncertainty": "Mock 演示：没有独立时间线，不推断真实日期",
                    }
                )

        no_observation = []
        for part in core:
            part_id = str(part.get("part_id"))
            if part_id in covered_parts:
                continue
            reason = (
                "非目标人物发言，只作上下文"
                if part.get("speaker") != target
                else "Mock 未从该片段生成演示观察"
            )
            no_observation.append({"part_id": part_id, "reason": reason})

        message_ids: list[str] = []
        for part in core:
            message_id = str(part.get("message_id"))
            if message_id not in message_ids:
                message_ids.append(message_id)
        candidates = []
        if len(message_ids) >= 2:
            candidates.append(
                {
                    "message_ids": message_ids[:8],
                    "note": "Mock 演示片段，来自当前块的连续消息",
                }
            )

        return {
            "schema_version": "1.0",
            "chunk_id": chunk_id,
            "target": target,
            "processed_core_part_ids": [str(part.get("part_id")) for part in core],
            "observations": observations,
            "processed_no_observation": no_observation,
            "example_candidates": candidates,
            "unknowns": ["Mock 模式只做表面特征演示，未进行语义理解"],
            "overflow": False,
        }

    def _reduce(self, payload: dict[str, Any]) -> dict[str, Any]:
        dimension = str(payload.get("dimension", "language"))
        target = str(payload.get("target", ""))
        interlocutor = str(payload.get("interlocutor", ""))
        items = [item for item in payload.get("items", []) if isinstance(item, dict)]
        if not items:
            return {"features": [], "dispositions": []}

        groups: list[list[dict[str, Any]]] = []
        for item in items:
            if len(groups) < 2 and (not groups or len(groups[-1]) >= 3):
                groups.append([item])
            else:
                groups[-1].append(item)

        features: list[dict[str, Any]] = []
        dispositions: list[dict[str, Any]] = []
        for number, group in enumerate(groups, start=1):
            source_ids: list[str] = []
            refs: list[dict[str, Any]] = []
            counter_refs: list[dict[str, Any]] = []
            for item in group:
                if isinstance(item.get("observation_ids"), list):
                    source_ids.extend(str(x) for x in item["observation_ids"])
                else:
                    source_ids.append(str(item.get("id")))
                refs.extend(
                    ref for ref in item.get("evidence_refs", []) if isinstance(ref, dict)
                )
                counter_refs.extend(
                    ref for ref in item.get("counter_evidence_refs", []) if isinstance(ref, dict)
                )
            refs = _dedupe_refs(refs)
            if not refs:
                continue
            digest = hashlib.sha256(
                (dimension + "|" + "|".join(source_ids)).encode("utf-8")
            ).hexdigest()[:12]
            first = group[0]
            features.append(
                {
                    "id": f"f:{dimension}:{number}-{digest}",
                    "dimension": dimension,
                    "claim": str(first.get("claim", "材料不足，保持未知")),
                    "kind": str(first.get("kind", "observed_pattern")),
                    "observation_ids": source_ids,
                    "counter_observation_ids": [],
                    "evidence_refs": refs,
                    "confidence": str(first.get("confidence", "low")),
                    "scope": first.get(
                        "scope",
                        {
                            "interlocutor": interlocutor,
                            "message_start_id": None,
                            "message_end_id": None,
                            "situation": None,
                            "time_scope": None,
                        },
                    ),
                    "uncertainty": "Mock 演示：由表面观察合并，未做语义归纳",
                }
            )
            for item in group:
                dispositions.append(
                    {
                        "item_id": str(item.get("id")),
                        "disposition": "merged",
                        "feature_id": features[-1]["id"],
                    }
                )
        for item in items:
            item_id = str(item.get("id"))
            if not any(d["item_id"] == item_id for d in dispositions):
                dispositions.append(
                    {"item_id": item_id, "disposition": "retained", "feature_id": None}
                )
        return {
            "dimension": dimension,
            "target": target,
            "features": features,
            "dispositions": dispositions,
        }

    @staticmethod
    def _corrupt_evidence(data: dict[str, Any]) -> None:
        observations = data.get("observations")
        if isinstance(observations, list) and observations:
            refs = observations[0].get("evidence_refs")
            if isinstance(refs, list) and refs:
                refs[0]["end"] = int(refs[0].get("end", 0)) + 100000
                return
        features = data.get("features")
        if isinstance(features, list) and features:
            refs = features[0].get("evidence_refs")
            if isinstance(refs, list) and refs:
                refs[0]["end"] = int(refs[0].get("end", 0)) + 100000
