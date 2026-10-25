"""Sequential build/resume pipeline with checkpoints and evidence checks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from person_simulator import __version__
from person_simulator.budget import safety_margin
from person_simulator.chunking import ChunkPlan, build_chunk_plan
from person_simulator.config import Settings
from person_simulator.errors import (
    ConfigError,
    ContextLimitError,
    EvidenceError,
    InputError,
    OutputTruncatedError,
    PersonSimError,
    PipelineError,
    StorageError,
)
from person_simulator.modeling.extract import PROMPT_VERSION, run_extract
from person_simulator.modeling.persona import assemble_persona, build_examples, persona_stats
from person_simulator.modeling.reduce import batch_items, run_reduce
from person_simulator.modeling.validation import (
    ResolvedRef,
    VerifiedSegment,
    parse_json_object,
    resolve_ref,
    validate_reduce_output,
    validate_segment,
)
from person_simulator.models import (
    AnalysisStatus,
    Chunk,
    Coverage,
    Dimension,
    ExportStatus,
    Feature,
    Manifest,
    Message,
    MessagePart,
    Observation,
    Persona,
    QualityStatus,
    ReduceOutput,
    SegmentAnalysis,
    SourceRange,
    TaskState,
    TaskStatus,
)
from person_simulator.parser import ParsedChat, parse_chat
from person_simulator.providers import build_client
from person_simulator.providers.base import ModelClient
from person_simulator.providers.runner import RequestRunner
from person_simulator.rendering.markdown import (
    assert_self_contained,
    render_persona,
    render_system_prompt,
)
from person_simulator.storage import RunStore, analysis_filename, make_run_id, utcnow
from person_simulator.textstats import language_stats, stats_lines

DEFAULT_OUT = Path("runs")
SUPPORTED_MANIFEST_PACKAGE_VERSIONS = {"0.1.0", __version__}


@dataclass
class BuildResult:
    run_dir: Path
    manifest: Manifest
    persona: Persona | None
    export_path: Path | None
    report: dict[str, Any]
    system_prompt_path: Path | None = None


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _hash_model(model: Any) -> str:
    return _hash_payload(model.model_dump(mode="json"))


def _new_manifest(
    parsed: ParsedChat,
    *,
    target: str,
    interlocutor: str,
    settings: Settings,
    input_path: str,
) -> Manifest:
    now = utcnow()
    return Manifest(
        prompt_version=PROMPT_VERSION,
        package_version=__version__,
        run_id="pending",
        source_hash=parsed.source_hash,
        target=target,
        interlocutor=interlocutor,
        config_hash=settings.config_hash(),
        provider=settings.model.provider,
        model=settings.model.model,
        is_mock=settings.is_mock,
        budget={
            "context_window": settings.effective_context_window,
            "chunk_input_budget": settings.chunking.chunk_input_budget,
            "overlap_messages": settings.chunking.overlap_messages,
            "max_output_tokens": settings.model.max_output_tokens,
            "max_attempts": settings.retry.max_attempts,
            "max_repair_attempts": settings.budget.max_repair_attempts,
            "max_context_splits": settings.budget.max_context_splits,
            "max_requests_per_run": settings.budget.max_requests_per_run,
            "safety_margin": safety_margin(settings.effective_context_window),
            "estimation": "ceil(utf8_bytes*1.25)+512 packaging (heuristic, not a tokenizer)",
        },
        analysis_status=AnalysisStatus.PENDING,
        quality_status=QualityStatus.NOT_EVALUATED,
        export_status=ExportStatus.PENDING,
        input_path=input_path,
        created_at=now,
        updated_at=now,
    )


def _save_manifest(store: RunStore, manifest: Manifest) -> None:
    manifest.updated_at = utcnow()
    store.write_json("manifest.json", manifest)


def _record_task(
    store: RunStore,
    manifest: Manifest,
    task_id: str,
    task_type: str,
    *,
    depends_on: Iterable[str] = (),
    status: TaskStatus = TaskStatus.SUCCEEDED,
    attempts: int = 0,
    result_hash: str | None = None,
    error: str | None = None,
    error_code: str | None = None,
) -> None:
    manifest.tasks[task_id] = TaskState(
        task_id=task_id,
        task_type=task_type,
        status=status,
        depends_on=list(depends_on),
        attempts=attempts,
        result_hash=result_hash,
        error=error,
        error_code=error_code,
    )
    _save_manifest(store, manifest)


def _checkpoint_extract(store: RunStore, task_id: str, analysis: SegmentAnalysis) -> str:
    digest = _hash_model(analysis)
    store.write_json(analysis_filename(task_id), analysis.model_dump(mode="json"))
    return digest


def _cached_extract(
    store: RunStore,
    manifest: Manifest,
    task_id: str,
    *,
    chunk: Chunk,
    messages: dict[str, Message],
    parts: dict[str, MessagePart],
    target: str,
    interlocutor: str,
) -> VerifiedSegment | None:
    state = manifest.tasks.get(task_id)
    if state is None or state.status != TaskStatus.SUCCEEDED:
        return None
    try:
        payload = store.read_json(analysis_filename(task_id))
        analysis = SegmentAnalysis.model_validate(payload)
        verified = validate_segment(
            analysis,
            chunk=chunk,
            messages=messages,
            parts=parts,
            target=target,
            interlocutor=interlocutor,
        )
        if state.result_hash and _hash_model(analysis) != state.result_hash:
            raise EvidenceError("缓存结果哈希不一致", stage="resume", task_id=task_id)
        return verified
    except (StorageError, ValidationError, EvidenceError, PersonSimError):
        _record_task(
            store,
            manifest,
            task_id,
            "extract",
            status=TaskStatus.FAILED,
            error="缓存损坏或不匹配，已标记重算",
            error_code="E_CACHE",
        )
        return None


def _split_chunk(
    chunk: Chunk,
    *,
    parts: dict[str, MessagePart],
    messages: dict[str, Message],
    depth: int,
) -> tuple[Chunk, Chunk]:
    if len(chunk.core_parts) < 2:
        raise PipelineError(
            "单个 core part 无法继续拆分",
            stage="extract",
            task_id=f"extract:{chunk.id}",
            hint="缩小输入片段或提高上下文预算",
        )
    midpoint = len(chunk.core_parts) // 2
    halves = [chunk.core_parts[:midpoint], chunk.core_parts[midpoint:]]
    made: list[Chunk] = []
    for label, core in zip(("a", "b"), halves):
        first_part = parts[core[0]]
        last_part = parts[core[-1]]
        first = messages[first_part.message_id]
        last = messages[last_part.message_id]
        made.append(
            Chunk(
                id=f"{chunk.id}.s{depth + 1}{label}",
                core_parts=core,
                context_parts=[],
                source_range=SourceRange(
                    first_message_id=first.id,
                    last_message_id=last.id,
                    line_start=first.line_start,
                    line_end=last.line_end,
                ),
                budget_estimate=chunk.budget_estimate,
            )
        )
    return made[0], made[1]


def _run_extract_tree(
    store: RunStore,
    manifest: Manifest,
    runner: RequestRunner,
    settings: Settings,
    *,
    chunk: Chunk,
    messages: dict[str, Message],
    parts: dict[str, MessagePart],
    target: str,
    interlocutor: str,
    depth: int = 0,
) -> list[tuple[Chunk, VerifiedSegment]]:
    if depth > settings.budget.max_context_splits:
        raise PipelineError(
            "超过最大切分深度",
            stage="extract",
            task_id=f"extract:{chunk.id}",
            hint="缩小输入或提高 budget.max_context_splits",
        )
    task_id = f"extract:{chunk.id}"
    cached = _cached_extract(
        store,
        manifest,
        task_id,
        chunk=chunk,
        messages=messages,
        parts=parts,
        target=target,
        interlocutor=interlocutor,
    )
    if cached is not None:
        return [(chunk, cached)]

    before = runner.used
    try:
        verified = run_extract(
            runner,
            chunk=chunk,
            parts=parts,
            messages=messages,
            target=target,
            interlocutor=interlocutor,
            output_limit=settings.model.max_output_tokens,
            max_repairs=settings.budget.max_repair_attempts,
            context_window=settings.effective_context_window,
        )
    except OutputTruncatedError:
        left, right = _split_chunk(chunk, parts=parts, messages=messages, depth=depth)
        return _run_extract_tree(
            store, manifest, runner, settings,
            chunk=left, messages=messages, parts=parts,
            target=target, interlocutor=interlocutor, depth=depth + 1,
        ) + _run_extract_tree(
            store, manifest, runner, settings,
            chunk=right, messages=messages, parts=parts,
            target=target, interlocutor=interlocutor, depth=depth + 1,
        )
    except ContextLimitError:
        if chunk.context_parts:
            without_context = chunk.model_copy(
                update={"id": f"{chunk.id}.noctx", "context_parts": []}
            )
            return _run_extract_tree(
                store, manifest, runner, settings,
                chunk=without_context, messages=messages, parts=parts,
                target=target, interlocutor=interlocutor, depth=depth,
            )
        left, right = _split_chunk(chunk, parts=parts, messages=messages, depth=depth)
        return _run_extract_tree(
            store, manifest, runner, settings,
            chunk=left, messages=messages, parts=parts,
            target=target, interlocutor=interlocutor, depth=depth + 1,
        ) + _run_extract_tree(
            store, manifest, runner, settings,
            chunk=right, messages=messages, parts=parts,
            target=target, interlocutor=interlocutor, depth=depth + 1,
        )

    if verified.analysis.overflow:
        left, right = _split_chunk(chunk, parts=parts, messages=messages, depth=depth)
        return _run_extract_tree(
            store, manifest, runner, settings,
            chunk=left, messages=messages, parts=parts,
            target=target, interlocutor=interlocutor, depth=depth + 1,
        ) + _run_extract_tree(
            store, manifest, runner, settings,
            chunk=right, messages=messages, parts=parts,
            target=target, interlocutor=interlocutor, depth=depth + 1,
        )

    digest = _checkpoint_extract(store, task_id, verified.analysis)
    _record_task(
        store,
        manifest,
        task_id,
        "extract",
        attempts=max(1, runner.used - before),
        result_hash=digest,
    )
    return [(chunk, verified)]


def _reduce_task(
    store: RunStore,
    manifest: Manifest,
    runner: RequestRunner,
    settings: Settings,
    *,
    dimension: Dimension,
    target: str,
    interlocutor: str,
    items: list[dict[str, Any]],
    messages: dict[str, Message],
    level: int,
    batch: int,
    depends_on: list[str],
) -> tuple[ReduceOutput, str]:
    task_id = f"reduce:{dimension.value}:L{level}:B{batch}"
    input_hash = _hash_payload(
        {"dimension": dimension.value, "target": target, "items": items}
    )
    state = manifest.tasks.get(task_id)
    if state is not None and state.status == TaskStatus.SUCCEEDED:
        try:
            payload = store.read_json(analysis_filename(task_id))
            if payload.get("input_hash") == input_hash:
                output = ReduceOutput.model_validate(payload["output"])
                validate_reduce_output(
                    output,
                    items=items,
                    messages=messages,
                    target=target,
                    dimension=dimension,
                    task_id=task_id,
                )
                if not state.result_hash or state.result_hash == _hash_payload(payload["output"]):
                    return output, task_id
        except (StorageError, KeyError, TypeError, ValidationError, PersonSimError):
            pass
        _record_task(
            store,
            manifest,
            task_id,
            "reduce",
            status=TaskStatus.FAILED,
            error="缓存损坏或不匹配，已标记重算",
            error_code="E_CACHE",
        )

    before = runner.used
    output = run_reduce(
        runner,
        dimension=dimension,
        target=target,
        interlocutor=interlocutor,
        items=items,
        messages=messages,
        output_limit=settings.model.max_output_tokens,
        max_repairs=settings.budget.max_repair_attempts,
        context_window=settings.effective_context_window,
        level=level,
        batch=batch,
    )
    payload = {
        "input_hash": input_hash,
        "output": output.model_dump(mode="json"),
    }
    digest = _hash_payload(payload["output"])
    store.write_json(analysis_filename(task_id), payload)
    _record_task(
        store,
        manifest,
        task_id,
        "reduce",
        depends_on=depends_on,
        attempts=max(1, runner.used - before),
        result_hash=digest,
    )
    return output, task_id


def _reduce_dimension(
    store: RunStore,
    manifest: Manifest,
    runner: RequestRunner,
    settings: Settings,
    *,
    dimension: Dimension,
    target: str,
    interlocutor: str,
    observations: list[Observation],
    messages: dict[str, Message],
    extract_tasks: list[str],
) -> list[Feature]:
    items = [
        observation.model_dump(mode="json")
        for observation in observations
        if observation.dimension == dimension
    ]
    if not items:
        return []
    budget = (
        settings.effective_context_window
        - settings.model.max_output_tokens
        - safety_margin(settings.effective_context_window)
    )
    if budget <= 0:
        raise ConfigError("输出与安全预留耗尽上下文预算", stage="reduce")
    from person_simulator.modeling.extract import load_prompt, schema_text
    from person_simulator.models import ReduceOutput as _ReduceOutput

    prompt = load_prompt("reduce.txt").replace("{schema}", schema_text(_ReduceOutput))
    level = 0
    parents = extract_tasks
    while True:
        batches = batch_items(
            items,
            budget=budget,
            prompt=prompt,
            output_limit=settings.model.max_output_tokens,
        )
        if not batches:
            return []
        if level > 0 and all(len(batch) == 1 for batch in batches):
            return [Feature.model_validate(batch[0]) for batch in batches]
        outputs: list[ReduceOutput] = []
        task_ids: list[str] = []
        carried: list[Feature] = []
        called = 0
        for number, batch in enumerate(batches, start=1):
            if level > 0 and len(batch) == 1:
                carried.append(Feature.model_validate(batch[0]))
                continue
            called += 1
            output, task_id = _reduce_task(
                store,
                manifest,
                runner,
                settings,
                dimension=dimension,
                target=target,
                interlocutor=interlocutor,
                items=batch,
                messages=messages,
                level=level,
                batch=number,
                depends_on=parents,
            )
            outputs.append(output)
            task_ids.append(task_id)
        if len(batches) == 1:
            return outputs[0].features
        items = [feature.model_dump(mode="json") for feature in carried] + [
            feature.model_dump(mode="json")
            for output in outputs
            for feature in output.features
        ]
        if not items:
            return []
        parents = task_ids
        level += 1
        if level > settings.budget.max_context_splits:
            raise PipelineError(
                "汇总层级超过上限",
                stage="reduce",
                hint="提高 budget.max_context_splits 或缩小维度批次",
            )


def _validate_persona_evidence(
    persona: Persona,
    *,
    messages: dict[str, Message],
    observations: list[Observation],
) -> None:
    observation_ids = {observation.id for observation in observations}
    features = (
        persona.language
        + persona.behavior
        + persona.thinking
        + persona.emotion
        + persona.relationship
        + persona.history
        + persona.changes
        + persona.uncertainty
    )
    for feature in features:
        if not set(feature.observation_ids) <= observation_ids:
            raise EvidenceError(
                "Persona feature 追溯了不存在的观察",
                stage="persona",
                task_id=feature.id,
            )
        for ref in feature.evidence_refs:
            resolved = resolve_ref(ref, messages, task_id=feature.id)
        if not any(resolve_ref(ref, messages).speaker == persona.target for ref in feature.evidence_refs):
            raise EvidenceError(
                "Persona feature 缺少目标人物证据",
                stage="persona",
                task_id=feature.id,
            )


def _build_report_text(
    *,
    manifest: Manifest,
    persona: Persona | None,
    plan: ChunkPlan,
    coverage: Coverage,
    analyses: list[VerifiedSegment],
    features_by_dimension: dict[Dimension, list[Feature]],
    export_text: str | None,
    skipped_examples: list[str],
    messages: dict[str, Message],
    system_prompt_text: str | None = None,
) -> str:
    stats = persona_stats(persona) if persona else {"features": {}, "empty_dimensions": [], "examples": 0, "conflicts": 0}
    surface = language_stats(messages.values(), manifest.target)
    observations = [observation for analysis in analyses for observation in analysis.analysis.observations]
    dimension_counts = {
        dimension.value: len(features_by_dimension.get(dimension, []))
        for dimension in Dimension
    }
    lines = [
        "# build_report",
        "",
        f"- run_id: {manifest.run_id}",
        f"- mode: {'MOCK (synthetic)' if manifest.is_mock else 'api'}",
        f"- provider/model: {manifest.provider} / {manifest.model or 'mock'}",
        f"- target / interlocutor: {manifest.target} / {manifest.interlocutor}",
        f"- source_hash: {manifest.source_hash}",
        f"- analysis_status: {manifest.analysis_status.value}",
        f"- export_status: {manifest.export_status.value}",
        f"- quality_status: {manifest.quality_status.value}",
        "",
        "## 覆盖",
        "",
        f"- 原文消息: {coverage.total_messages}",
        f"- 目标消息: {coverage.target_messages}",
        f"- 目标正文字符: {coverage.total_chars}",
        f"- 覆盖字符: {coverage.covered_chars}",
        f"- coverage ratio: {coverage.ratio:.4f}",
        f"- 片段数: {len(plan.chunks)}",
        "",
        "## 语言统计（代码计算，分母为目标消息）",
        "",
        *stats_lines(surface),
        "",
        "## 证据与特征",
        "",
        f"- 成功提取任务: {len(analyses)}",
        f"- observations: {len(observations)}",
        f"- features: {sum(dimension_counts.values())}",
        f"- 空维度: {', '.join(stats['empty_dimensions']) or '无'}",
        f"- 未进入导出提示词的观察: {stats.get('conflicts', 0)}",
        f"- 示例数: {stats.get('examples', 0)}",
        "- 示例选择理由: 优先覆盖日常/亲近/冲突/拒绝/修复情境，最多 12 段；被跳过的候选原因见本节末尾。",
        "- 未保留历史范围: 未进入最终提示词的观察保留在 persona.json 的 selection_audit；导出只含被选中特征与示例。",
        "",
        "| 维度 | feature 数 | observation 数 |",
        "|---|---:|---:|",
    ]
    for dimension in Dimension:
        count = sum(
            1 for observation in observations if observation.dimension == dimension
        )
        lines.append(f"| {dimension.value} | {dimension_counts[dimension.value]} | {count} |")
    lines.extend(
        [
            "",
            "## 导出",
            "",
            f"- 字符数: {len(export_text) if export_text else 0}",
            f"- UTF-8 字节数: {len(export_text.encode('utf-8')) if export_text else 0}",
            f"- 软目标 32000 字符: {'超出，未截断' if export_text and len(export_text) > 32000 else '未超出'}",
            f"- 独立系统提示词: {len(system_prompt_text) if system_prompt_text else 0} 字符（system_prompt.md）",
        ]
    )
    if skipped_examples:
        lines.append(f"- 被跳过的示例候选: {len(skipped_examples)}（{skipped_examples[0]}）")
    lines.extend(
        [
            "",
            "## 状态与限制",
            "",
            "- Mock 通过只证明管线可运行，不证明真实人物相似度。",
            "- 结构校验与证据回源通过不等于语义解释正确。",
            f"- 真实 API 状态: {'not_run (mock 模式)' if manifest.is_mock else '已配置并按调用执行；仍需独立验收'}",
            "- quality_status 保持 not_evaluated，除非另有真实人工评估。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(store: RunStore, text: str) -> None:
    store.write_text("build_report.md", text)


def _execute(
    store: RunStore,
    manifest: Manifest,
    parsed: ParsedChat,
    plan: ChunkPlan,
    settings: Settings,
    client: ModelClient,
    *,
    runner: RequestRunner | None = None,
) -> BuildResult:
    manifest.analysis_status = AnalysisStatus.RUNNING
    manifest.export_status = ExportStatus.PENDING
    _save_manifest(store, manifest)
    messages = {message.id: message for message in parsed.messages}
    parts = {part.id: part for part in plan.parts}
    runner = runner or RequestRunner(
        client,
        max_attempts=settings.retry.max_attempts,
        max_requests=settings.budget.max_requests_per_run,
    )

    analyses: list[VerifiedSegment] = []
    leaf_chunks: list[Chunk] = []
    try:
        for chunk in plan.chunks:
            leaves = _run_extract_tree(
                store,
                manifest,
                runner,
                settings,
                chunk=chunk,
                messages=messages,
                parts=parts,
                target=manifest.target,
                interlocutor=manifest.interlocutor,
            )
            for leaf_chunk, verified in leaves:
                leaf_chunks.append(leaf_chunk)
                analyses.append(verified)

        leaf_part_ids = [
            part_id
            for verified in analyses
            for part_id in verified.analysis.processed_core_part_ids
        ]
        if sorted(leaf_part_ids) != sorted(part.id for part in plan.parts):
            raise PipelineError(
                "成功叶子任务没有恰好覆盖全部 core parts",
                stage="coverage",
                hint="检查拆分与检查点；不完整时不得发布",
            )

        observations = [
            observation
            for verified in analyses
            for observation in verified.analysis.observations
        ]
        observation_ids = [observation.id for observation in observations]
        if len(set(observation_ids)) != len(observation_ids):
            raise EvidenceError("不同片段产生了重复 observation ID", stage="coverage")

        evidence_records = [
            record for verified in analyses for record in verified.evidence
        ]
        store.write_jsonl("evidence.jsonl", evidence_records)
        store.write_jsonl(
            "observations.jsonl",
            [observation.model_dump(mode="json") for observation in observations],
        )

        features_by_dimension: dict[Dimension, list[Feature]] = {}
        for dimension in Dimension:
            dimension_observations = [
                observation
                for observation in observations
                if observation.dimension == dimension
            ]
            if not dimension_observations:
                features_by_dimension[dimension] = []
                continue
            extract_tasks = [
                f"extract:{verified.analysis.chunk_id}"
                for verified in analyses
                if verified.analysis.chunk_id.startswith("c")
                and any(
                    observation.dimension == dimension
                    for observation in verified.analysis.observations
                )
            ]
            features_by_dimension[dimension] = _reduce_dimension(
                store,
                manifest,
                runner,
                settings,
                dimension=dimension,
                target=manifest.target,
                interlocutor=manifest.interlocutor,
                observations=observations,
                messages=messages,
                extract_tasks=extract_tasks,
            )

        candidates = [
            candidate
            for verified in analyses
            for candidate in verified.analysis.example_candidates
        ]
        all_features = [
            feature
            for dimension_features in features_by_dimension.values()
            for feature in dimension_features
        ]
        store.write_jsonl(
            "features_all.jsonl",
            [feature.model_dump(mode="json") for feature in all_features],
        )
        examples, skipped_examples = build_examples(
            candidates,
            messages=messages,
            message_order=[message.id for message in parsed.messages],
            target=manifest.target,
        )
        unknowns = [
            unknown for verified in analyses for unknown in verified.analysis.unknowns
        ]
        persona = assemble_persona(
            target=manifest.target,
            interlocutor=manifest.interlocutor,
            source_hash=parsed.source_hash,
            coverage=plan.coverage,
            features_by_dimension=features_by_dimension,
            observations=observations,
            examples=examples,
            unknowns=unknowns,
        )
        _validate_persona_evidence(
            persona, messages=messages, observations=observations
        )
        store.write_json("persona.json", persona)
        manifest.coverage = plan.coverage
        manifest.analysis_status = AnalysisStatus.COMPLETE

        draft_report = _build_report_text(
            manifest=manifest,
            persona=persona,
            plan=plan,
            coverage=plan.coverage,
            analyses=analyses,
            features_by_dimension=features_by_dimension,
            export_text=None,
            skipped_examples=skipped_examples,
            messages=messages,
        )
        _write_report(store, draft_report)

        export_text = render_persona(
            persona,
            manifest,
            messages,
            observations=observations,
        )
        assert_self_contained(export_text)
        system_prompt_text = render_system_prompt(persona, messages)
        assert_self_contained(system_prompt_text)
        target_path = store._path("person_simulation.md")
        prompt_path = store._path("system_prompt.md")
        store.write_text("person_simulation.md", export_text)
        store.write_text("system_prompt.md", system_prompt_text)
        try:
            manifest.export_status = ExportStatus.COMPLETE
            _save_manifest(store, manifest)
        except Exception:
            target_path.unlink(missing_ok=True)
            prompt_path.unlink(missing_ok=True)
            raise

        report_text = _build_report_text(
            manifest=manifest,
            persona=persona,
            plan=plan,
            coverage=plan.coverage,
            analyses=analyses,
            features_by_dimension=features_by_dimension,
            export_text=export_text,
            skipped_examples=skipped_examples,
            messages=messages,
            system_prompt_text=system_prompt_text,
        )
        _write_report(store, report_text)
        return BuildResult(
            run_dir=store.path,
            manifest=manifest,
            persona=persona,
            export_path=target_path,
            report={
                "characters": len(export_text),
                "bytes": len(export_text.encode("utf-8")),
                "over_soft_limit": len(export_text) > 32000,
                "observations": len(observations),
                "features": sum(len(value) for value in features_by_dimension.values()),
                "examples": len(examples),
                "requests_used": runner.used,
                "stats": persona_stats(persona),
                "language_stats": language_stats(parsed.messages, manifest.target).as_dict(),
                "system_prompt_characters": len(system_prompt_text),
            },
            system_prompt_path=prompt_path,
        )
    except KeyboardInterrupt:
        manifest.analysis_status = AnalysisStatus.INCOMPLETE
        manifest.export_status = ExportStatus.FAILED
        _save_manifest(store, manifest)
        (store.path / "person_simulation.md").unlink(missing_ok=True)
        raise
    except BaseException as exc:
        manifest.analysis_status = AnalysisStatus.INCOMPLETE
        manifest.export_status = ExportStatus.FAILED
        _save_manifest(store, manifest)
        (store.path / "person_simulation.md").unlink(missing_ok=True)
        raise


def build_run(
    input_path: str | Path,
    *,
    target: str,
    speaker_a: str = "A",
    speaker_b: str = "B",
    settings: Settings,
    out_root: str | Path = DEFAULT_OUT,
    client: ModelClient | None = None,
    runner: RequestRunner | None = None,
) -> BuildResult:
    parsed = parse_chat(input_path, speaker_a, speaker_b, target=target)
    interlocutor = (
        parsed.speaker_b if target == parsed.speaker_a else parsed.speaker_a
    )
    plan = build_chunk_plan(
        parsed,
        target,
        chunk_input_budget=settings.chunking.chunk_input_budget,
        overlap_messages=settings.chunking.overlap_messages,
    )
    if not plan.coverage.complete:
        raise InputError("原文覆盖不完整，拒绝构建", stage="chunking")
    manifest = _new_manifest(
        parsed,
        target=target,
        interlocutor=interlocutor,
        settings=settings,
        input_path=str(Path(input_path).resolve()),
    )
    run_id = make_run_id(target, parsed.source_hash)
    store = RunStore.create(Path(out_root), run_id)
    manifest.run_id = store.path.name
    try:
        store.write_jsonl("messages.jsonl", [message.model_dump(mode="json") for message in parsed.messages])
        store.write_jsonl("chunks.jsonl", [chunk.model_dump(mode="json") for chunk in plan.chunks])
        _save_manifest(store, manifest)
        active_client = client or build_client(settings)
        try:
            return _execute(store, manifest, parsed, plan, settings, active_client, runner=runner)
        finally:
            close = getattr(active_client, "close", None)
            if callable(close):
                close()
    finally:
        store.release_lock()


def _verify_resume_fingerprint(manifest: Manifest, settings: Settings) -> None:
    if manifest.config_hash != settings.config_hash():
        raise ConfigError(
            "resume 的配置与运行指纹不一致",
            stage="resume",
            hint="使用相同配置，或开始新的 run",
        )
    if (
        manifest.prompt_version != PROMPT_VERSION
        or manifest.package_version not in SUPPORTED_MANIFEST_PACKAGE_VERSIONS
    ):
        raise ConfigError("resume 的 prompt/package 版本不一致", stage="resume")
    if manifest.is_mock != settings.is_mock:
        raise ConfigError("resume 的运行模式不一致", stage="resume")


def _load_parsed(store: RunStore, manifest: Manifest) -> ParsedChat:
    rows = store.read_jsonl("messages.jsonl")
    try:
        messages = [Message.model_validate(row) for row in rows]
    except ValidationError as exc:
        raise StorageError("messages.jsonl 损坏", stage="resume") from exc
    if not messages:
        raise StorageError("messages.jsonl 为空", stage="resume")
    return ParsedChat(
        messages=messages,
        warnings=[],
        source_hash=manifest.source_hash,
        speaker_a=manifest.target,
        speaker_b=manifest.interlocutor,
    )


def _load_plan(store: RunStore, parsed: ParsedChat, manifest: Manifest, settings: Settings) -> ChunkPlan:
    plan = build_chunk_plan(
        parsed,
        manifest.target,
        chunk_input_budget=settings.chunking.chunk_input_budget,
        overlap_messages=settings.chunking.overlap_messages,
    )
    rows = store.read_jsonl("chunks.jsonl")
    try:
        stored = [Chunk.model_validate(row) for row in rows]
    except ValidationError as exc:
        raise StorageError("chunks.jsonl 损坏", stage="resume") from exc
    if [chunk.id for chunk in stored] != [chunk.id for chunk in plan.chunks]:
        raise ConfigError(
            "resume 重新切分的结果与已保存 chunks 不一致",
            stage="resume",
            hint="检查 chunking 配置；不要跨参数复用旧 run",
        )
    return plan


def resume_run(
    run_dir: str | Path,
    *,
    settings: Settings,
    client: ModelClient | None = None,
    runner: RequestRunner | None = None,
) -> BuildResult:
    store = RunStore.open(Path(run_dir))
    store.acquire_lock()
    try:
        try:
            manifest = Manifest.model_validate(store.read_json("manifest.json"))
        except ValidationError as exc:
            raise StorageError("manifest.json 损坏", stage="resume") from exc
        _verify_resume_fingerprint(manifest, settings)
        parsed = _load_parsed(store, manifest)
        plan = _load_plan(store, parsed, manifest, settings)
        if (
            manifest.export_status == ExportStatus.COMPLETE
            and store.exists("persona.json")
            and store.exists("person_simulation.md")
            and store.exists("system_prompt.md")
        ):
            persona = Persona.model_validate(store.read_json("persona.json"))
            return BuildResult(
                run_dir=store.path,
                manifest=manifest,
                persona=persona,
                export_path=store.path / "person_simulation.md",
                system_prompt_path=store.path / "system_prompt.md",
                report={"resumed": True, "already_complete": True},
            )
        manifest.run_id = store.path.name
        active_client = client or build_client(settings)
        try:
            result = _execute(store, manifest, parsed, plan, settings, active_client, runner=runner)
            result.report["resumed"] = True
            return result
        finally:
            close = getattr(active_client, "close", None)
            if callable(close):
                close()
    finally:
        store.release_lock()


def render_run(run_dir: str | Path, out_dir: str | Path) -> Path:
    store = RunStore.open(Path(run_dir))
    manifest = Manifest.model_validate(store.read_json("manifest.json"))
    if manifest.analysis_status != AnalysisStatus.COMPLETE or manifest.export_status != ExportStatus.COMPLETE:
        raise PipelineError(
            "运行未完成，拒绝渲染正式文件",
            stage="render",
            hint="先 resume 完成分析",
        )
    persona = Persona.model_validate(store.read_json("persona.json"))
    messages = {
        row["id"]: Message.model_validate(row) for row in store.read_jsonl("messages.jsonl")
    }
    observations: list[Observation] = []
    if store.exists("observations.jsonl"):
        observations = [
            Observation.model_validate(row) for row in store.read_jsonl("observations.jsonl")
        ]
    text = render_persona(persona, manifest, messages, observations=observations)
    assert_self_contained(text)
    system_prompt = render_system_prompt(persona, messages)
    assert_self_contained(system_prompt)
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    targets = [
        (destination / "person_simulation.md", text),
        (destination / "system_prompt.md", system_prompt),
    ]
    for target, _ in targets:
        if target.exists():
            raise StorageError("导出文件已存在，拒绝覆盖", stage="render", hint=str(target))
    written: list[Path] = []
    temporary: Path | None = None
    try:
        for target, content in targets:
            temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            written.append(target)
    except OSError as exc:
        for path in written:
            path.unlink(missing_ok=True)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise StorageError("导出写入失败", stage="render", hint=str(target)) from exc
    return destination / "person_simulation.md"
