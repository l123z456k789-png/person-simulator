"""Hierarchical reduce tasks with input-budget batching."""

from __future__ import annotations

import json
from typing import Any

from person_simulator.budget import (
    estimate_request_tokens,
    estimate_tokens,
    validate_context_budget,
)
from person_simulator.errors import PipelineError
from person_simulator.models import Dimension, Feature, Message, ReduceOutput
from person_simulator.modeling.extract import call_with_repair, load_prompt, schema_text
from person_simulator.modeling.validation import (
    parse_json_object,
    parse_reduce_output,
    validate_reduce_output,
)
from person_simulator.providers.base import ModelRequest
from person_simulator.providers.runner import RequestRunner


def build_reduce_request(
    *,
    dimension: Dimension,
    target: str,
    interlocutor: str,
    items: list[dict[str, Any]],
    output_limit: int,
    level: int,
    batch: int,
    prompt: str | None = None,
) -> ModelRequest:
    schema = schema_text(ReduceOutput)
    system = (prompt or load_prompt("reduce.txt")).replace("{schema}", schema)
    payload = {
        "task": "reduce",
        "dimension": dimension.value,
        "target": target,
        "interlocutor": interlocutor,
        "level": level,
        "items": items,
    }
    return ModelRequest(
        task_id=f"reduce:{dimension.value}:L{level}:B{batch}",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        output_limit=output_limit,
        schema=schema,
        capabilities={"json_object": True},
    )


def run_reduce(
    runner: RequestRunner,
    *,
    dimension: Dimension,
    target: str,
    interlocutor: str,
    items: list[dict[str, Any]],
    messages: dict[str, Message],
    output_limit: int,
    max_repairs: int,
    context_window: int,
    level: int,
    batch: int,
) -> ReduceOutput:
    request = build_reduce_request(
        dimension=dimension,
        target=target,
        interlocutor=interlocutor,
        items=items,
        output_limit=output_limit,
        level=level,
        batch=batch,
    )
    estimated = estimate_request_tokens(
        request.messages[0]["content"], request.messages[1]["content"], ""
    )
    validate_context_budget(
        estimated,
        output_limit,
        context_window,
        label=request.task_id,
    )

    def validator(content: str) -> ReduceOutput:
        payload = parse_json_object(content, task_id=request.task_id)
        output = parse_reduce_output(payload, task_id=request.task_id)
        validate_reduce_output(
            output,
            items=items,
            messages=messages,
            target=target,
            dimension=dimension,
            task_id=request.task_id,
        )
        return output

    return call_with_repair(
        runner,
        request,
        validator,
        max_repairs=max_repairs,
        context_window=context_window,
        output_limit=output_limit,
    )


def batch_items(
    items: list[dict[str, Any]],
    *,
    budget: int,
    prompt: str,
    output_limit: int,
) -> list[list[dict[str, Any]]]:
    """Greedy batching by estimated serialized size, preserving order."""
    if not items:
        return []
    system = prompt
    schema = schema_text(ReduceOutput)
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for item in items:
        trial = current + [item]
        estimated = estimate_request_tokens(
            system,
            json.dumps({"task": "reduce", "items": trial}, ensure_ascii=False),
            "",
        )
        if current and estimated + output_limit > budget:
            batches.append(current)
            current = [item]
        else:
            current = trial
    if current:
        batches.append(current)
    return batches


def split_oversized_item(item: dict[str, Any], max_tokens: int) -> list[dict[str, Any]]:
    """Split an oversized observation by evidence refs, never by rewriting text."""
    refs = [ref for ref in item.get("evidence_refs", []) if isinstance(ref, dict)]
    if len(refs) < 2:
        raise PipelineError(
            "单条观察过大且无法再拆",
            stage="reduce",
            hint="缩小 chunk_input_budget 或减少单条证据跨度",
        )
    base_id = str(item.get("id"))
    pieces: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for ref in refs:
        trial = current + [ref]
        clone = dict(item)
        clone["id"] = f"{base_id}.part{len(pieces) + 1}"
        clone["evidence_refs"] = trial
        if current and estimate_tokens(json.dumps(clone, ensure_ascii=False)) > max_tokens:
            clone["evidence_refs"] = current
            pieces.append(clone)
            current = [ref]
        else:
            current = trial
    if current:
        clone = dict(item)
        clone["id"] = f"{base_id}.part{len(pieces) + 1}"
        clone["evidence_refs"] = current
        pieces.append(clone)
    return pieces
