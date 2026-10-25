"""Map task: extract traceable observations from one chunk."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Callable

from person_simulator.budget import estimate_request_tokens, validate_context_budget
from person_simulator.errors import EvidenceError, ResponseFormatError
from person_simulator.models import Chunk, Message, MessagePart, SegmentAnalysis
from person_simulator.modeling.validation import (
    VerifiedSegment,
    parse_json_object,
    parse_segment_analysis,
    validate_segment,
)
from person_simulator.providers.base import ModelRequest
from person_simulator.providers.runner import RequestRunner

PROMPT_VERSION = "1.0"


def load_prompt(name: str) -> str:
    return files("person_simulator.prompts").joinpath(name).read_text(encoding="utf-8")


def schema_text(model: type) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2)


def _part_payload(part: MessagePart, message: Message) -> list[object]:
    """Compact array: [part_id, speaker, start, end, text]."""
    return [part.id, message.speaker, part.start, part.end, part.text]


def build_extract_payload(
    chunk: Chunk,
    *,
    parts: dict[str, MessagePart],
    messages: dict[str, Message],
    target: str,
    interlocutor: str,
) -> dict[str, Any]:
    core = [
        _part_payload(parts[part_id], messages[parts[part_id].message_id])
        for part_id in chunk.core_parts
    ]
    context = [
        _part_payload(parts[part_id], messages[parts[part_id].message_id])
        for part_id in chunk.context_parts
    ]
    return {
        "task": "extract",
        "chunk_id": chunk.id,
        "target": target,
        "interlocutor": interlocutor,
        "core_parts": core,
        "context_parts": context,
    }


def build_extract_request(
    chunk: Chunk,
    *,
    parts: dict[str, MessagePart],
    messages: dict[str, Message],
    target: str,
    interlocutor: str,
    output_limit: int,
    prompt: str | None = None,
) -> ModelRequest:
    schema = schema_text(SegmentAnalysis)
    system = (prompt or load_prompt("extract.txt")).replace("{schema}", schema)
    payload = build_extract_payload(
        chunk,
        parts=parts,
        messages=messages,
        target=target,
        interlocutor=interlocutor,
    )
    return ModelRequest(
        task_id=f"extract:{chunk.id}",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        output_limit=output_limit,
        schema=schema,
        capabilities={"json_object": True},
    )


def _repair_messages(request: ModelRequest, response_text: str, error_text: str) -> list[dict[str, str]]:
    return [
        *request.messages,
        {"role": "assistant", "content": response_text},
        {
            "role": "user",
            "content": (
                "上一次响应未通过校验。\n"
                f"校验错误：{error_text}\n"
                "请只返回修正后的完整 JSON 对象；不要解释，不要放宽字段，不要添加不存在的证据。"
            ),
        },
    ]


def call_with_repair(
    runner: RequestRunner,
    request: ModelRequest,
    validator: Callable[[str], Any],
    *,
    max_repairs: int,
    context_window: int,
    output_limit: int,
) -> Any:
    response = runner.call(request)
    last_error: Exception | None = None
    for attempt in range(max_repairs + 1):
        try:
            return validator(response.content)
        except (ResponseFormatError, EvidenceError) as exc:
            last_error = exc
            if attempt >= max_repairs:
                break
            messages = _repair_messages(request, response.content, str(exc))
            estimated = estimate_request_tokens(
                messages[0]["content"],
                "\n".join(message["content"] for message in messages[1:]),
                "",
            )
            try:
                validate_context_budget(
                    estimated,
                    output_limit,
                    context_window,
                    label=f"{request.task_id} 修复请求",
                )
            except Exception:
                break
            repair_request = ModelRequest(
                task_id=f"{request.task_id}:repair{attempt + 1}",
                messages=messages,
                output_limit=output_limit,
                schema=request.schema,
                capabilities=request.capabilities,
            )
            response = runner.call(repair_request)
    if last_error is not None:
        raise last_error
    raise ResponseFormatError("校验未产生结果", stage="modeling", task_id=request.task_id)


def run_extract(
    runner: RequestRunner,
    *,
    chunk: Chunk,
    parts: dict[str, MessagePart],
    messages: dict[str, Message],
    target: str,
    interlocutor: str,
    output_limit: int,
    max_repairs: int,
    context_window: int,
) -> VerifiedSegment:
    request = build_extract_request(
        chunk,
        parts=parts,
        messages=messages,
        target=target,
        interlocutor=interlocutor,
        output_limit=output_limit,
    )
    estimated = estimate_request_tokens(
        request.messages[0]["content"], request.messages[1]["content"], ""
    )
    validate_context_budget(estimated, output_limit, context_window, label=request.task_id)

    def validator(content: str) -> VerifiedSegment:
        payload = parse_json_object(content, task_id=request.task_id)
        analysis = parse_segment_analysis(payload, task_id=request.task_id)
        return validate_segment(
            analysis,
            chunk=chunk,
            messages=messages,
            parts=parts,
            target=target,
            interlocutor=interlocutor,
        )

    return call_with_repair(
        runner,
        request,
        validator,
        max_repairs=max_repairs,
        context_window=context_window,
        output_limit=output_limit,
    )
