"""Whole-chat build and simulation pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from person_simulator.budget import PACKAGING_MARGIN, estimate_tokens, safety_margin, validate_context_budget
from person_simulator.config import Settings
from person_simulator.errors import (
    ConfigError,
    InputError,
    PipelineError,
    ResponseFormatError,
    RunModeError,
)
from person_simulator.models import Message
from person_simulator.parser import ParsedChat, parse_chat
from person_simulator.providers import build_client
from person_simulator.providers.base import ModelClient, ModelRequest
from person_simulator.providers.runner import RequestRunner
from person_simulator.runtime.persona import load_runtime_persona
from person_simulator.storage import RunStore, make_run_id, utcnow
from person_simulator.wholechat.prompts import (
    ANALYSIS_SYSTEM,
    RAW_SIMULATION_SYSTEM,
    build_analysis_user,
)
from person_simulator.wholechat.transcript import Transcript, serialize_transcript
from person_simulator.wholechat.verify import extract_tag, verify_whole_output

PROMPT_VERSION = "whole-1.0"


@dataclass
class WholeBuildResult:
    run_dir: Path
    system_prompt_path: Path
    profile_path: Path | None
    report_path: Path
    manifest: dict[str, Any]
    transcript: Transcript


def whole_request_estimate(
    *,
    transcript: Transcript,
    settings: Settings,
    system: str = ANALYSIS_SYSTEM,
) -> int:
    # The transcript estimate is calibrated; do not add its bytes a second time.
    return PACKAGING_MARGIN + estimate_tokens(system) + transcript.estimated_tokens + 256


def whole_fits(
    parsed: ParsedChat,
    settings: Settings,
    *,
    limit: int | None = None,
) -> tuple[bool, Transcript]:
    transcript = serialize_transcript(parsed.messages, limit=limit)
    required = (
        whole_request_estimate(transcript=transcript, settings=settings)
        + settings.model.max_output_tokens
        + safety_margin(settings.effective_context_window)
    )
    return required <= settings.effective_context_window, transcript


def _manifest(
    *,
    run_id: str,
    parsed: ParsedChat,
    target: str,
    interlocutor: str,
    settings: Settings,
    transcript: Transcript,
) -> dict[str, Any]:
    now = utcnow().isoformat()
    return {
        "schema_version": "whole-1.0",
        "strategy": "whole",
        "run_id": run_id,
        "source_hash": parsed.source_hash,
        "target": target,
        "interlocutor": interlocutor,
        "provider": settings.model.provider,
        "model": settings.model.model,
        "is_mock": settings.is_mock,
        "message_count": transcript.message_count,
        "char_count": transcript.char_count,
        "estimated_input_tokens": transcript.estimated_tokens,
        "token_estimate": transcript.as_dict(),
        "limited": transcript.limited,
        "status": "running",
        "created_at": now,
        "updated_at": now,
    }


def build_whole(
    input_path: str | Path,
    *,
    target: str,
    speaker_a: str = "A",
    speaker_b: str = "B",
    settings: Settings,
    out_root: str | Path = "runs",
    client: ModelClient | None = None,
    limit_messages: int | None = None,
) -> WholeBuildResult:
    parsed = parse_chat(input_path, speaker_a, speaker_b, target=target)
    interlocutor = parsed.speaker_b if target == parsed.speaker_a else parsed.speaker_a
    transcript = serialize_transcript(parsed.messages, limit=limit_messages)
    if transcript.message_count == 0:
        raise InputError("没有可分析的消息", stage="wholechat")
    user = build_analysis_user(
        transcript=transcript.text,
        target=target,
        interlocutor=interlocutor,
        message_count=transcript.message_count,
    )
    estimated = whole_request_estimate(
        transcript=transcript,
        settings=settings,
        system=ANALYSIS_SYSTEM,
    )
    validate_context_budget(
        estimated,
        settings.model.max_output_tokens,
        settings.effective_context_window,
        label="whole-chat analysis",
    )

    run_id = f"whole-{make_run_id(target, parsed.source_hash)}"
    store = RunStore.create(Path(out_root), run_id)
    manifest = _manifest(
        run_id=store.path.name,
        parsed=parsed,
        target=target,
        interlocutor=interlocutor,
        settings=settings,
        transcript=transcript,
    )
    try:
        store.write_json("manifest.json", manifest)
        active = client or build_client(settings)
        runner = RequestRunner(
            active,
            max_attempts=settings.retry.max_attempts,
            max_requests=max(3, settings.budget.max_requests_per_run),
        )
        try:
            response = runner.call(
                ModelRequest(
                    task_id="whole:analysis",
                    messages=[
                        {"role": "system", "content": ANALYSIS_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    output_limit=settings.model.max_output_tokens,
                    capabilities={"json_object": False},
                )
            )
        finally:
            close = getattr(active, "close", None)
            if callable(close):
                close()

        system_prompt = extract_tag(response.content, "system_prompt")
        profile = extract_tag(response.content, "person_simulation")
        if not system_prompt:
            raise ResponseFormatError(
                "模型没有返回 <system_prompt> 标签",
                stage="wholechat",
                task_id="whole:analysis",
                hint="要求模型严格输出两个标签",
            )
        refs = verify_whole_output(
            response_text=response.content,
            system_prompt=system_prompt,
            profile=profile,
            messages={message.id: message for message in parsed.messages},
            is_mock=settings.is_mock,
        )

        system_path = store.write_text("system_prompt.md", system_prompt + "\n")
        profile_path = (
            store.write_text("person_simulation.md", profile + "\n") if profile else None
        )
        usage = response.usage or {}
        report = [
            "# whole-chat build report",
            "",
            f"- strategy: whole",
            f"- target / interlocutor: {target} / {interlocutor}",
            f"- provider / model: {settings.model.provider} / {settings.model.model or 'mock'}",
            f"- is_mock: {settings.is_mock}",
            f"- source_hash: {parsed.source_hash}",
            f"- messages: {transcript.message_count}",
            f"- characters: {transcript.char_count}",
            f"- estimated input tokens: {transcript.estimated_tokens} (conservative heuristic)",
            f"- actual prompt tokens: {usage.get('prompt_tokens', 'unknown')}",
            f"- actual completion tokens: {usage.get('completion_tokens', 'unknown')}",
            f"- limited: {transcript.limited}",
            f"- message refs verified: {len(refs)}",
            f"- system_prompt.md: {len(system_prompt)} characters",
            f"- person_simulation.md: {len(profile) if profile else 0} characters",
            "",
            "## Notes",
            "",
            "- Whole-chat mode sends the original transcript directly; no chunk-map-reduce layer.",
            "- The system prompt is model-generated; structural checks do not prove persona quality.",
            "- quality_status: not_evaluated",
            "",
        ]
        report_path = store.write_text("build_report.md", "\n".join(report))
        manifest.update(
            {
                "status": "complete",
                "updated_at": utcnow().isoformat(),
                "usage": usage,
                "message_refs": refs,
                "system_prompt_chars": len(system_prompt),
                "profile_chars": len(profile) if profile else 0,
            }
        )
        store.write_json("manifest.json", manifest)
        return WholeBuildResult(
            run_dir=store.path,
            system_prompt_path=system_path,
            profile_path=profile_path,
            report_path=report_path,
            manifest=manifest,
            transcript=transcript,
        )
    except BaseException:
        manifest.update({"status": "failed", "updated_at": utcnow().isoformat()})
        try:
            store.write_json("manifest.json", manifest)
        except Exception:
            pass
        raise
    finally:
        store.release_lock()


def simulate_run(
    run_dir: str | Path,
    message: str,
    *,
    settings: Settings,
    client: ModelClient | None = None,
) -> str:
    loaded = load_runtime_persona(run_dir)
    if loaded.persona.is_mock != settings.is_mock:
        raise RunModeError(
            "run 的 Mock/API 模式与当前 simulate 模式不一致",
            stage="simulate",
            hint="Mock run 使用 --mode mock；真实 run 使用 --mode api",
        )
    system_prompt = loaded.persona.system_prompt
    active = client or build_client(settings)
    try:
        runner = RequestRunner(
            active,
            max_attempts=settings.retry.max_attempts,
            max_requests=3,
        )
        response = runner.call(
            ModelRequest(
                task_id="whole:simulate",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
                output_limit=settings.model.max_output_tokens,
            )
        )
    finally:
        close = getattr(active, "close", None)
        if callable(close):
            close()
    return response.content


def simulate_raw(
    input_path: str | Path,
    *,
    target: str,
    speaker_a: str,
    speaker_b: str,
    message: str,
    settings: Settings,
    client: ModelClient | None = None,
) -> str:
    parsed = parse_chat(input_path, speaker_a, speaker_b, target=target)
    transcript = serialize_transcript(parsed.messages)
    system = RAW_SIMULATION_SYSTEM.format(transcript=transcript.text)
    intro = RAW_SIMULATION_SYSTEM.format(transcript="")
    estimated = (
        PACKAGING_MARGIN
        + estimate_tokens(intro)
        + transcript.estimated_tokens
        + estimate_tokens(message)
        + 256
    )
    validate_context_budget(
        estimated,
        settings.model.max_output_tokens,
        settings.effective_context_window,
        label="raw simulation",
    )
    active = client or build_client(settings)
    try:
        runner = RequestRunner(
            active,
            max_attempts=settings.retry.max_attempts,
            max_requests=3,
        )
        response = runner.call(
            ModelRequest(
                task_id="whole:simulate_raw",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": message},
                ],
                output_limit=settings.model.max_output_tokens,
            )
        )
    finally:
        close = getattr(active, "close", None)
        if callable(close):
            close()
    return response.content
