"""Command line interface."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import secrets
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from person_simulator import __version__
from person_simulator.chunking import build_chunk_plan
from person_simulator.config import SimulationSettings, load_settings
from person_simulator.errors import (
    ConfigError,
    ContextLimitError,
    PersonSimError,
    PipelineError,
    RunModeError,
    StorageError,
)
from person_simulator.evaluation.prepare import prepare_eval
from person_simulator.evaluation.score import score_eval, write_quality_report
from person_simulator.models import Manifest
from person_simulator.parser import parse_chat
from person_simulator.pipeline import build_run, render_run, resume_run
from person_simulator.privacy import PrivacyMode, scan_text
from person_simulator.progress import ProgressCallback, ProgressEvent
from person_simulator.providers import build_client
from person_simulator.providers.base import ModelRequest
from person_simulator.runtime.client import AdminClient, SimulationClient
from person_simulator.runtime.invite import (
    InvitePayload,
    read_invite,
    write_invite,
)
from person_simulator.runtime.models import Audience
from person_simulator.runtime.persona import load_runtime_persona
from person_simulator.runtime.service import build_model_messages
from person_simulator.runs import delete_run, inspect_run, list_runs, purge_runs
from person_simulator.server import InviteRegistry, create_server
from person_simulator.storage import RunStore
from person_simulator.wholechat.pipeline import (
    build_whole,
    simulate_raw,
    simulate_run,
    whole_fits,
)

CONFIG_CLI_KEYS = (
    "mode",
    "provider",
    "model",
    "base_url",
    "context_window",
    "max_output_tokens",
    "chunk_input_budget",
    "overlap_messages",
    "max_attempts",
    "allow_insecure_localhost",
    "disable_thinking",
)


def _add_input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True, help="UTF-8 双人聊天 .txt/.md")
    parser.add_argument("--speaker-a", default="A", help="第一个说话人标签（默认 A）")
    parser.add_argument("--speaker-b", default="B", help="第二个说话人标签（默认 B）")
    parser.add_argument("--target", required=True, help="要建模的人物标签（必填）")


def _add_config_args(
    parser: argparse.ArgumentParser,
    *,
    with_mode: bool = False,
    with_max_requests: bool = True,
) -> None:
    parser.add_argument("--config", help="TOML 配置文件")
    if with_mode:
        parser.add_argument("--mode", choices=["mock", "api"], help="运行模式；默认取配置")
    parser.add_argument("--provider", choices=["mock", "openai_chat"])
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--context-window", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--chunk-input-budget", type=int)
    parser.add_argument("--overlap-messages", type=int)
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--disable-thinking", action="store_true", default=None)
    parser.add_argument("--allow-insecure-localhost", action="store_true", default=None)
    if with_max_requests:
        parser.add_argument("--max-requests", type=int, help="本次运行最大请求尝试数")


def _overrides(args: argparse.Namespace) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in CONFIG_CLI_KEYS:
        if hasattr(args, key):
            value = getattr(args, key)
            if value is not None:
                values[key] = value
    return values


def _settings(args: argparse.Namespace):
    return load_settings(config_path=getattr(args, "config", None), cli_overrides=_overrides(args))


def _privacy_mode(args: argparse.Namespace) -> PrivacyMode:
    if getattr(args, "redact_pii", False):
        return "redact"
    if getattr(args, "privacy_strict", False):
        return "block"
    return "warn"


def _progress_callback(args: argparse.Namespace) -> ProgressCallback | None:
    if getattr(args, "json_progress", False):
        def emit_json(event: ProgressEvent) -> None:
            print(
                json.dumps(event.as_dict(), ensure_ascii=False),
                file=sys.stderr,
            )

        return emit_json
    if getattr(args, "progress", False):
        def emit_text(event: ProgressEvent) -> None:
            position = ""
            if event.current is not None and event.total is not None:
                position = f" {event.current}/{event.total}"
            requests = (
                f" requests={event.requests_used}"
                if event.requests_used is not None
                else ""
            )
            print(
                f"progress {event.stage}{position} {event.message}{requests}",
                file=sys.stderr,
            )

        return emit_text
    return None


def _print_privacy(report: dict[str, object], mode: PrivacyMode) -> None:
    total = int(report.get("total", 0) or 0)
    print(f"privacy_findings {total}")
    if mode == "redact" and total:
        print(f"privacy_redacted {total}")
    elif mode == "warn" and total:
        print(
            "privacy_warning 导出文件包含直接身份信息；请使用 --redact-pii 脱敏，"
            "或先清理原始聊天。未回显具体内容。",
            file=sys.stderr,
        )


def _print_error(exc: PersonSimError) -> None:
    print(str(exc), file=sys.stderr)


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = _settings(args)
    summary = settings.public_summary()
    print(f"person-simulator {__version__}")
    print(f"python {platform.python_version()}")
    print(f"cwd {Path.cwd()}")
    print(f"config_path {summary['config_path'] or 'none'}")
    print(f"mode {summary['mode']}")
    print(f"provider {summary['provider']}")
    print(f"model {summary['model'] or 'none'}")
    print(f"base_url_host {summary['base_url_host'] or 'none'}")
    print(f"context_window {summary['effective_context_window']}")
    print(f"max_output_tokens {summary['max_output_tokens']}")
    print(f"chunk_input_budget {summary['chunk_input_budget']}")
    print(f"overlap_messages {summary['overlap_messages']}")
    print(f"api_key_present {'yes' if summary['api_key_present'] else 'no'}")
    print("sources " + json.dumps(summary["sources"], ensure_ascii=False, sort_keys=True))
    if args.probe_api:
        if settings.model.mode != "api":
            raise ConfigError(
                "--probe-api 仅用于 api 模式",
                stage="doctor",
                hint="显式设置 --mode api 并提供配置",
            )
        if not settings.api_key:
            raise ConfigError("缺少 PSIM_API_KEY，无法探测", stage="doctor")
        client = build_client(settings)
        try:
            response = client.complete(
                ModelRequest(
                    task_id="doctor-probe",
                    messages=[{"role": "user", "content": "Reply with OK only."}],
                    output_limit=16,
                )
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        print(f"probe_status ok provider={response.provider} request_id={response.request_id or 'unknown'}")
    else:
        print("probe_status skipped (default offline; use --probe-api explicitly)")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    parsed = parse_chat(
        args.input,
        args.speaker_a,
        args.speaker_b,
        target=args.target,
    )
    target_count = sum(1 for message in parsed.messages if message.speaker == args.target)
    print(f"speaker_a {parsed.speaker_a}")
    print(f"speaker_b {parsed.speaker_b}")
    print(f"target {args.target}")
    print(f"messages {len(parsed.messages)}")
    print(f"target_messages {target_count}")
    print(f"sessions {len({message.session_id for message in parsed.messages})}")
    print(f"warnings {len(parsed.warnings)}")
    for warning in parsed.warnings:
        print(f"warning: {warning}")
    print("status valid")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    settings = _settings(args)
    parsed = parse_chat(
        args.input,
        args.speaker_a,
        args.speaker_b,
        target=args.target,
    )
    plan = build_chunk_plan(
        parsed,
        args.target,
        chunk_input_budget=settings.chunking.chunk_input_budget,
        overlap_messages=settings.chunking.overlap_messages,
    )
    print(f"target {args.target}")
    print(f"messages {len(parsed.messages)}")
    print(f"chunks {len(plan.chunks)}")
    print(f"parts {len(plan.parts)}")
    print(f"budget_method ceil(utf8_bytes*1.25)+512 packaging; not a tokenizer")
    print(f"context_window {settings.effective_context_window}")
    print(f"chunk_input_budget {settings.chunking.chunk_input_budget}")
    print(f"coverage_ratio {plan.coverage.ratio:.4f}")
    print(f"coverage_complete {str(plan.coverage.complete).lower()}")
    print(f"map_calls_lower_bound {plan.map_call_lower_bound}")
    max_requests = settings.budget.max_requests_per_run
    print(f"max_requests_per_run {max_requests}")
    if plan.map_call_lower_bound > max_requests:
        print(
            f"warning map_calls_lower_bound={plan.map_call_lower_bound} 超过 max_requests_per_run={max_requests}；"
            "build 会在达到上限时保留检查点并退出，请提高 --max-requests 或 chunk_input_budget"
        )
    elif plan.map_call_lower_bound * 1.5 > max_requests:
        print(
            f"warning map_calls_lower_bound={plan.map_call_lower_bound} 已接近 max_requests_per_run={max_requests}；"
            "汇总、修复和重试还会增加调用，建议显式提高 --max-requests"
        )
    print("note reduce/repair/retry calls are not included; no price estimate")
    if not plan.coverage.complete:
        raise PipelineError("切分覆盖不完整", stage="plan")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    settings = _settings(args)
    privacy_mode = _privacy_mode(args)
    progress = _progress_callback(args)
    if args.max_requests is not None:
        settings.budget.max_requests_per_run = args.max_requests
    if settings.model.mode == "api" and not settings.api_key:
        raise ConfigError(
            "api 模式需要 PSIM_API_KEY；不会自动降级为 mock",
            stage="build",
            hint="设置环境变量 PSIM_API_KEY，或显式使用 --mode mock",
        )
    strategy = args.strategy
    if strategy == "auto":
        parsed = parse_chat(
            args.input, args.speaker_a, args.speaker_b, target=args.target
        )
        fits, _ = whole_fits(parsed, settings, limit=args.limit_messages)
        strategy = "whole" if fits else "evidence"
        print(f"strategy auto -> {strategy}")
    if strategy == "whole":
        result = build_whole(
            args.input,
            target=args.target,
            speaker_a=args.speaker_a,
            speaker_b=args.speaker_b,
            settings=settings,
            out_root=args.out,
            limit_messages=args.limit_messages,
            privacy_mode=privacy_mode,
            progress=progress,
        )
        print("status completed")
        print(f"strategy whole")
        _print_privacy(result.manifest.get("privacy", {}), privacy_mode)
        print(f"run_dir {result.run_dir}")
        print(f"system_prompt {result.system_prompt_path}")
        if result.profile_path:
            print(f"person_simulation {result.profile_path}")
        print(f"messages {result.transcript.message_count}")
        print(f"limited {str(result.transcript.limited).lower()}")
        if result.manifest.get("is_mock"):
            print("MOCK 合成演示，不代表真实人物建模")
        return 0

    result = build_run(
        args.input,
        target=args.target,
        speaker_a=args.speaker_a,
        speaker_b=args.speaker_b,
        settings=settings,
        out_root=args.out,
        privacy_mode=privacy_mode,
        progress=progress,
        limit_messages=args.limit_messages,
    )
    print(f"status completed")
    print(f"run_dir {result.run_dir}")
    print(f"limited {str(result.report.get('limited', False)).lower()}")
    print(f"source_messages {result.report.get('source_messages', 0)}")
    print(f"analyzed_messages {result.report.get('analyzed_messages', 0)}")
    _print_privacy(result.report.get("privacy", {}), privacy_mode)
    print(f"export {result.export_path}")
    print(f"analysis_status {result.manifest.analysis_status.value}")
    print(f"export_status {result.manifest.export_status.value}")
    print(f"quality_status {result.manifest.quality_status.value}")
    print(f"characters {result.report.get('characters', 0)}")
    print(f"bytes {result.report.get('bytes', 0)}")
    print(f"requests_used {result.report.get('requests_used', 0)}")
    if result.manifest.is_mock:
        print("MOCK 合成演示，不代表真实人物建模")
    if result.system_prompt_path:
        print(f"system_prompt {result.system_prompt_path}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    if args.unlock:
        store = RunStore.open(Path(args.run))
        print(store.unlock_stale())
        return 0
    settings = _settings(args)
    privacy_mode = _privacy_mode(args)
    progress = _progress_callback(args)
    if args.max_requests is not None:
        settings.budget.max_requests_per_run = args.max_requests
    if settings.model.mode == "api" and not settings.api_key:
        raise ConfigError("api 模式需要 PSIM_API_KEY", stage="resume")
    result = resume_run(
        args.run,
        settings=settings,
        privacy_mode=privacy_mode,
        progress=progress,
    )
    print("status completed")
    print(f"run_dir {result.run_dir}")
    _print_privacy(result.report.get("privacy", {}), privacy_mode)
    print(f"export {result.export_path}")
    print(f"analysis_status {result.manifest.analysis_status.value}")
    print(f"export_status {result.manifest.export_status.value}")
    if result.system_prompt_path:
        print(f"system_prompt {result.system_prompt_path}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    privacy_mode = _privacy_mode(args)
    progress = _progress_callback(args)
    path = render_run(
        args.run,
        args.out,
        privacy_mode=privacy_mode,
        progress=progress,
    )
    text = path.read_text(encoding="utf-8")
    prompt_path = path.parent / "system_prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    report = scan_text(text + "\n" + prompt)
    print(f"export {path}")
    print(f"system_prompt {prompt_path}")
    print(f"characters {len(text)}")
    print(f"bytes {len(text.encode('utf-8'))}")
    _print_privacy(report.as_dict(), privacy_mode)
    return 0


def cmd_runs_list(args: argparse.Namespace) -> int:
    summaries = list_runs(args.root)
    if args.json:
        print(
            json.dumps(
                [summary.as_dict() for summary in summaries],
                ensure_ascii=False,
            )
        )
        return 0
    print("run_id\tstrategy\tstatus\ttarget\tmock\tlimited\tlocked\tsize\texport")
    for summary in summaries:
        print(
            f"{summary.run_id}\t{summary.strategy}\t{summary.status}\t"
            f"{summary.target or '-'}\t{str(summary.is_mock).lower()}\t"
            f"{str(summary.limited).lower()}\t{str(summary.locked).lower()}\t"
            f"{summary.size_bytes}\t{str(summary.has_export).lower()}"
        )
    return 0


def cmd_runs_status(args: argparse.Namespace) -> int:
    detail = inspect_run(args.run, root=args.root)
    if args.json:
        print(json.dumps(detail.as_dict(), ensure_ascii=False))
        return 0
    summary = detail.summary
    print(f"run_id {summary.run_id}")
    print(f"path {summary.path}")
    print(f"strategy {summary.strategy}")
    print(f"status {summary.status}")
    print(f"target {summary.target or 'none'}")
    print(f"is_mock {str(summary.is_mock).lower()}")
    print(f"limited {str(summary.limited).lower()}")
    print(f"created_at {summary.created_at or 'unknown'}")
    print(f"updated_at {summary.updated_at or 'unknown'}")
    print(f"size_bytes {summary.size_bytes}")
    print(f"locked {str(summary.locked).lower()}")
    print(f"lock_pid {summary.lock_pid or 'none'}")
    for status, count in sorted(detail.task_counts.items()):
        print(f"tasks_{status} {count}")
    for name, present in detail.files.items():
        print(f"file_{name} {str(present).lower()}")
    if detail.manifest_error:
        print(f"manifest_error {detail.manifest_error}", file=sys.stderr)
    return 0


def cmd_runs_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ConfigError(
            "删除 run 需要显式 --yes",
            stage="runs",
            hint="先用 runs status 确认目标；本命令不可撤销",
        )
    delete_run(args.run, root=args.root, force=args.force)
    print(f"deleted {args.run}")
    return 0


def cmd_runs_purge(args: argparse.Namespace) -> int:
    statuses = tuple(args.status or ())
    selected = purge_runs(
        args.root,
        statuses=statuses,
        older_than_days=args.older_than_days,
        all_runs=args.all,
        apply=False,
    )
    if not selected:
        print("no runs matched")
        return 0
    if not args.yes:
        for summary in selected:
            print(f"would_delete {summary.run_id}\t{summary.status}")
        print(f"matched {len(selected)}; 使用 --yes 执行删除")
        return 0
    deleted = purge_runs(
        args.root,
        statuses=statuses,
        older_than_days=args.older_than_days,
        all_runs=args.all,
        apply=True,
        force=args.force,
    )
    for summary in deleted:
        print(f"deleted {summary.run_id}")
    return 0


def cmd_eval_prepare(args: argparse.Namespace) -> int:
    result = prepare_eval(
        args.input,
        target=args.target,
        speaker_a=args.speaker_a,
        speaker_b=args.speaker_b,
        out=args.out,
    )
    print(f"bundle {result.bundle}")
    print(f"status {result.status}")
    print(f"cases {result.cases}")
    if result.reason:
        print(f"reason {result.reason}")
    print(f"guide {result.bundle / 'evaluation_guide.md'}")
    if result.status != "prepared":
        print("评估包不足，需人工准备更多会话或材料", file=sys.stderr)
        return 4
    return 0


def cmd_eval_score(args: argparse.Namespace) -> int:
    report = score_eval(
        bundle=args.bundle,
        responses_path=args.responses,
        ratings_path=args.ratings,
    )
    json_path, md_path = write_quality_report(report, args.bundle)
    print(f"status {report['status']}")
    print(f"gate_passed {str(report['gate_passed']).lower()}")
    print(f"quality_report {json_path}")
    print(f"quality_report_md {md_path}")
    for dimension, values in report["dimensions"].items():
        print(
            f"dimension {dimension} mean={values['mean']} count={values['count']}"
        )
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if settings.model.mode == "api" and not settings.api_key:
        raise ConfigError("api 模式需要 PSIM_API_KEY", stage="simulate")
    if args.run and args.input:
        raise ConfigError("--run 与 --input 只能二选一", stage="simulate")
    if args.run:
        text = simulate_run(args.run, args.message, settings=settings)
    elif args.input:
        if not args.target:
            raise ConfigError("--input 模式需要 --target", stage="simulate")
        text = simulate_raw(
            args.input,
            target=args.target,
            speaker_a=args.speaker_a,
            speaker_b=args.speaker_b,
            message=args.message,
            settings=settings,
        )
    else:
        raise ConfigError("需要 --run 或 --input", stage="simulate")
    print(text)
    return 0


def _admin_token(args: argparse.Namespace, *, generate: bool = False) -> tuple[str, str]:
    path = getattr(args, "admin_token_file", None)
    if path:
        try:
            token = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(
                "管理员令牌文件不可读", stage="admin", hint=str(path)
            ) from exc
        if not token:
            raise ConfigError("管理员令牌文件为空", stage="admin", hint=str(path))
        return token, "file"
    token = os.environ.get("PSIM_ADMIN_TOKEN")
    if token:
        return token, "env"
    if generate:
        return secrets.token_urlsafe(32), "generated"
    raise ConfigError(
        "缺少管理员令牌",
        stage="admin",
        hint="设置 PSIM_ADMIN_TOKEN 或使用 --admin-token-file",
    )


def _invite_passphrase(args: argparse.Namespace) -> str:
    env_name = getattr(args, "passphrase_env", "PSIM_INVITE_PASSPHRASE")
    value = os.environ.get(env_name)
    if value:
        return value
    if not sys.stdin.isatty():
        raise ConfigError(
            "缺少邀请口令",
            stage="invite",
            hint=f"设置环境变量 {env_name}，或在交互终端运行",
        )
    value = getpass.getpass("邀请口令: ")
    if not value:
        raise ConfigError("邀请口令不能为空", stage="invite")
    return value


def _apply_simulation_args(settings, args: argparse.Namespace) -> None:
    updates: dict[str, Any] = {}
    for attr in (
        "host",
        "port",
        "allow_lan",
        "secure_cookies",
        "max_sessions",
        "max_turns",
        "max_input_chars",
        "requests_per_minute",
        "max_concurrency",
    ):
        value = getattr(args, attr, None)
        if value is not None:
            updates[attr] = value
    sim_output = getattr(args, "sim_max_output_tokens", None)
    if sim_output is not None:
        updates["max_output_tokens"] = sim_output
    if getattr(args, "allowed_host", None):
        updates["allowed_hosts"] = [
            *settings.simulation.allowed_hosts,
            *args.allowed_host,
        ]
    if updates:
        try:
            settings.simulation = SimulationSettings.model_validate(
                {**settings.simulation.model_dump(), **updates}
            )
        except ValidationError as exc:
            raise ConfigError(
                "simulation 配置无效",
                stage="serve",
                hint=str(exc),
            ) from exc


def _check_public_bind(settings) -> None:
    if (
        settings.simulation.host not in {"127.0.0.1", "localhost", "::1"}
        and not settings.simulation.allow_lan
    ):
        raise ConfigError(
            "非 loopback 监听需要显式 --allow-lan",
            stage="serve",
            hint="默认只允许 127.0.0.1；局域网请显式开启",
        )


def cmd_serve(args: argparse.Namespace) -> int:
    settings = _settings(args)
    _apply_simulation_args(settings, args)
    _check_public_bind(settings)
    loaded = load_runtime_persona(args.run, audience=args.audience)
    if loaded.persona.is_mock != settings.is_mock:
        raise RunModeError(
            "run 的 Mock/API 模式与当前 --mode 不一致",
            stage="serve",
            hint="Mock run 使用 --mode mock；真实 run 使用 --mode api",
        )
    if settings.model.mode == "api" and not settings.api_key:
        raise ConfigError(
            "api 模式需要 PSIM_API_KEY；不会自动降级为 mock",
            stage="serve",
        )
    output_limit = min(
        settings.simulation.max_output_tokens,
        settings.model.max_output_tokens,
    )
    try:
        build_model_messages(
            loaded.persona.system_prompt,
            [],
            "",
            context_window=settings.effective_context_window,
            output_limit=output_limit,
        )
    except ContextLimitError as exc:
        raise ConfigError(
            "运行时上下文预算不足",
            stage="serve",
            hint=str(exc),
        ) from exc
    if args.check:
        print("status ready")
        print(f"runtime_schema {loaded.persona.schema_version}")
        print(f"run_id {loaded.persona.run_id}")
        print(f"strategy {loaded.persona.strategy}")
        print(f"audience {loaded.persona.audience.value}")
        print(f"is_mock {str(loaded.persona.is_mock).lower()}")
        print(f"replay_guard {loaded.persona.replay_guard}")
        print(f"host {settings.simulation.host}")
        print(f"port {settings.simulation.port}")
        return 0

    admin_token, source = _admin_token(args, generate=True)
    server = create_server(
        persona=loaded.persona,
        settings=settings,
        host=settings.simulation.host,
        port=settings.simulation.port,
        registry=InviteRegistry(),
        admin_token=admin_token,
        replay_messages=loaded.replay_messages,
    )
    if not settings.simulation.blocked_terms:
        print(
            "warning blocked_terms 为空：姓名/地址等非正则身份信息不会被自动隐藏",
            file=sys.stderr,
        )
    print("status ready")
    print(f"run_id {loaded.persona.run_id}")
    print(f"public_url {server.public_url}")
    for lan_url in server.lan_urls:
        print(f"lan_url {lan_url}")
    print(f"admin_url {server.admin_url}")
    print(f"admin_token_source {source}")
    if source == "generated":
        print(f"admin_token {admin_token}")
    print(
        "next "
        f"person-sim invite create --server {server.admin_url} "
        f"--endpoint {server.public_url} --out invite.psim"
    )
    try:
        server.serve_forever()
    finally:
        server.shutdown()
    print("status stopped")
    return 0


def cmd_invite_create(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        raise StorageError("邀请文件已存在，拒绝覆盖", stage="invite", hint=str(out))
    token, _ = _admin_token(args)
    passphrase = _invite_passphrase(args)
    admin = AdminClient(args.server, token)
    try:
        created = admin.create_invite(
            label=args.label,
            expires_in_seconds=args.expires_in,
            max_sessions=args.max_sessions,
        )
    finally:
        admin.close()
    payload = InvitePayload(
        endpoint=args.endpoint,
        token=str(created["token"]),
        expires_at=datetime.fromisoformat(str(created["expires_at"])),
        label=str(created.get("label", args.label)),
        max_sessions=args.max_sessions,
    )
    payload.ensure_valid()
    write_invite(out, payload, passphrase)
    endpoint = args.endpoint.rstrip("/")
    print(f"invite {out}")
    print(f"invite_id {created['invite_id']}")
    print(f"web_url {endpoint}/?token={payload.token}")
    print(f"expires_at {payload.expires_at.isoformat()}")
    return 0


def cmd_invite_list(args: argparse.Namespace) -> int:
    token, _ = _admin_token(args)
    admin = AdminClient(args.server, token)
    try:
        rows = admin.list_invites()
    finally:
        admin.close()
    for row in rows:
        print(
            f"{row.get('id')} revoked={row.get('revoked')} "
            f"expires={row.get('expires_at')} label={row.get('label')}"
        )
    return 0


def cmd_invite_revoke(args: argparse.Namespace) -> int:
    token, _ = _admin_token(args)
    admin = AdminClient(args.server, token)
    try:
        admin.revoke_invite(args.invite_id)
    finally:
        admin.close()
    print(f"revoked {args.invite_id}")
    return 0


def _print_notices(notices: object) -> None:
    if isinstance(notices, list):
        for notice in notices:
            print(f"notice: {notice}", file=sys.stderr)


def cmd_connect(args: argparse.Namespace) -> int:
    passphrase = _invite_passphrase(args)
    payload = read_invite(args.invite, passphrase)
    client = SimulationClient(payload.endpoint, payload.token)
    try:
        client.create_session()
        if args.message:
            reply = client.chat(args.message)
            print(reply["reply"])
            _print_notices(reply.get("notices"))
            client.end_session()
            return 0

        print("输入 /exit 结束会话。", file=sys.stderr)
        while True:
            try:
                text = input("你: ")
            except (EOFError, KeyboardInterrupt):
                break
            if text.strip() in {"/exit", "/quit"}:
                break
            if not text.strip():
                continue
            reply = client.chat(text)
            print(f"模拟: {reply['reply']}")
            _print_notices(reply.get("notices"))
        client.end_session()
        return 0
    finally:
        client.close()


def cmd_session_list(args: argparse.Namespace) -> int:
    token, _ = _admin_token(args)
    admin = AdminClient(args.server, token)
    try:
        rows = admin.list_sessions()
    finally:
        admin.close()
    for row in rows:
        print(
            f"{row.get('id')} state={row.get('state')} "
            f"turns={row.get('turns')} invite={row.get('invite_id')}"
        )
    return 0


def cmd_session_delete(args: argparse.Namespace) -> int:
    token, _ = _admin_token(args)
    admin = AdminClient(args.server, token)
    try:
        admin.delete_session(args.session_id)
    finally:
        admin.close()
    print(f"deleted {args.session_id}")
    return 0


def _add_progress_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--progress",
        action="store_true",
        help="向 stderr 输出人类可读的构建进度",
    )
    group.add_argument(
        "--json-progress",
        action="store_true",
        help="向 stderr 输出 JSON Lines 进度事件",
    )


def _add_privacy_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--redact-pii",
        action="store_true",
        help="替换导出文件中的手机号/身份证/邮箱/座机/银行卡，并提示数量",
    )
    group.add_argument(
        "--privacy-strict",
        action="store_true",
        help="导出前发现直接身份信息就拒绝发布",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="person-sim",
        description="把预清洗的双人聊天转换为可独立使用的角色扮演 Markdown。",
    )
    parser.add_argument("--version", action="version", version=f"person-simulator {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="检查环境与配置（默认不联网）")
    _add_config_args(doctor)
    doctor.add_argument("--probe-api", action="store_true", help="显式发送最小真实 API 探测")
    doctor.set_defaults(func=cmd_doctor)

    validate = subparsers.add_parser("validate", help="校验输入、说话人与 target")
    _add_input_args(validate)
    validate.set_defaults(func=cmd_validate)

    plan = subparsers.add_parser("plan", help="离线输出切分与预算计划")
    _add_input_args(plan)
    _add_config_args(plan)
    plan.set_defaults(func=cmd_plan)

    build = subparsers.add_parser("build", help="构建人物资料与 person_simulation.md")
    _add_input_args(build)
    _add_config_args(build, with_mode=True)
    build.add_argument("--out", default="runs", help="运行目录根（默认 runs）")
    build.add_argument(
        "--strategy",
        choices=["auto", "whole", "evidence"],
        default="auto",
        help="whole=整段原文，evidence=分片证据流水线，auto=按上下文预算选择",
    )
    build.add_argument(
        "--limit-messages",
        type=int,
        default=None,
        help="只分析前 N 条消息（用于 30–50 条 pilot）",
    )
    _add_privacy_args(build)
    _add_progress_args(build)
    build.set_defaults(func=cmd_build)

    resume = subparsers.add_parser("resume", help="从检查点恢复运行")
    resume.add_argument("--run", required=True)
    _add_config_args(resume, with_mode=True)
    resume.add_argument("--unlock", action="store_true", help="显式移除已确认陈旧的锁")
    _add_privacy_args(resume)
    _add_progress_args(resume)
    resume.set_defaults(func=cmd_resume)

    render_command = subparsers.add_parser("render", help="从已完成的 run 导出 Markdown")
    render_command.add_argument("--run", required=True)
    render_command.add_argument("--out", required=True)
    _add_privacy_args(render_command)
    _add_progress_args(render_command)
    render_command.set_defaults(func=cmd_render)

    runs_parser = subparsers.add_parser("runs", help="查看、删除或清理 run 目录")
    runs_sub = runs_parser.add_subparsers(dest="runs_command", required=True)

    runs_list = runs_sub.add_parser("list", help="列出 run 元数据")
    runs_list.add_argument("--root", default="runs")
    runs_list.add_argument("--json", action="store_true")
    runs_list.set_defaults(func=cmd_runs_list)

    runs_status = runs_sub.add_parser("status", help="查看单个 run 状态")
    runs_status.add_argument("run")
    runs_status.add_argument("--root", default="runs")
    runs_status.add_argument("--json", action="store_true")
    runs_status.set_defaults(func=cmd_runs_status)

    runs_delete = runs_sub.add_parser("delete", help="删除单个 run（需要 --yes）")
    runs_delete.add_argument("run")
    runs_delete.add_argument("--root", default="runs")
    runs_delete.add_argument("--yes", action="store_true")
    runs_delete.add_argument(
        "--force",
        action="store_true",
        help="清理已确认陈旧的锁后再删除；仍拒绝活动进程",
    )
    runs_delete.set_defaults(func=cmd_runs_delete)

    runs_purge = runs_sub.add_parser("purge", help="按条件批量清理 run")
    runs_purge.add_argument("--root", default="runs")
    runs_purge.add_argument(
        "--status",
        action="append",
        choices=["complete", "incomplete", "failed", "running", "invalid"],
        default=None,
    )
    runs_purge.add_argument("--older-than-days", type=int, default=None)
    runs_purge.add_argument("--all", action="store_true", help="选择全部 run")
    runs_purge.add_argument("--yes", action="store_true")
    runs_purge.add_argument("--force", action="store_true")
    runs_purge.set_defaults(func=cmd_runs_purge)

    simulate = subparsers.add_parser("simulate", help="用已生成提示词或原始聊天模拟回应")
    simulate.add_argument("--run", help="whole/evidence run 目录（使用 system_prompt.md）")
    simulate.add_argument("--input", help="原始聊天文件（原文驱动模拟）")
    simulate.add_argument("--target")
    simulate.add_argument("--speaker-a", default="A")
    simulate.add_argument("--speaker-b", default="B")
    simulate.add_argument("--message", required=True, help="当前新消息/情境")
    _add_config_args(simulate, with_mode=True)
    simulate.set_defaults(func=cmd_simulate)

    eval_parser = subparsers.add_parser("eval", help="准备或汇总人工评估")
    eval_sub = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_prepare = eval_sub.add_parser("prepare", help="生成留出评估包")
    _add_input_args(eval_prepare)
    eval_prepare.add_argument("--out", required=True)
    eval_prepare.set_defaults(func=cmd_eval_prepare)
    eval_score = eval_sub.add_parser("score", help="汇总人工回答与评分")
    eval_score.add_argument("--bundle", required=True)
    eval_score.add_argument("--responses", required=True)
    eval_score.add_argument("--ratings", required=True)
    eval_score.set_defaults(func=cmd_eval_score)

    serve = subparsers.add_parser("serve", help="启动去中心化第三方模拟服务")
    serve.add_argument("--run", required=True, help="已完成且通过校验的 run 目录")
    serve.add_argument("--check", action="store_true", help="只校验 run 与配置，不监听")
    _add_config_args(serve, with_mode=True, with_max_requests=False)
    serve.add_argument("--host", help="监听地址；默认取配置，通常 127.0.0.1")
    serve.add_argument("--port", type=int, help="公开监听端口")
    serve.add_argument("--allow-lan", action="store_true", default=None)
    serve.add_argument("--secure-cookies", action="store_true", default=None)
    serve.add_argument(
        "--audience",
        choices=["guest", "original"],
        default="guest",
        help="第三方默认观众：guest 或 original",
    )
    serve.add_argument(
        "--allowed-host",
        action="append",
        default=None,
        help="额外允许的 Host（隧道域名可重复传入）",
    )
    serve.add_argument("--max-sessions", type=int)
    serve.add_argument("--max-turns", type=int)
    serve.add_argument("--max-input-chars", type=int)
    serve.add_argument("--sim-max-output-tokens", type=int)
    serve.add_argument("--requests-per-minute", type=int)
    serve.add_argument("--max-concurrency", type=int)
    serve.add_argument("--admin-token-file")
    serve.set_defaults(func=cmd_serve)

    invite_parser = subparsers.add_parser("invite", help="创建或撤销加密邀请")
    invite_sub = invite_parser.add_subparsers(
        dest="invite_command", required=True
    )
    invite_create = invite_sub.add_parser("create", help="创建加密邀请文件")
    invite_create.add_argument("--server", required=True, help="管理员接口地址")
    invite_create.add_argument("--endpoint", required=True, help="C 可访问的公开地址")
    invite_create.add_argument("--out", required=True, help="邀请文件输出路径")
    invite_create.add_argument("--label", default="", help="邀请备注")
    invite_create.add_argument("--expires-in", type=int, default=3600)
    invite_create.add_argument("--max-sessions", type=int, default=None)
    invite_create.add_argument(
        "--passphrase-env", default="PSIM_INVITE_PASSPHRASE"
    )
    invite_create.add_argument("--admin-token-file")
    invite_create.set_defaults(func=cmd_invite_create)

    invite_list = invite_sub.add_parser("list", help="列出邀请元数据")
    invite_list.add_argument("--server", required=True)
    invite_list.add_argument("--admin-token-file")
    invite_list.set_defaults(func=cmd_invite_list)

    invite_revoke = invite_sub.add_parser("revoke", help="撤销邀请")
    invite_revoke.add_argument("--server", required=True)
    invite_revoke.add_argument("--invite-id", required=True)
    invite_revoke.add_argument("--admin-token-file")
    invite_revoke.set_defaults(func=cmd_invite_revoke)

    connect = subparsers.add_parser(
        "connect", help="解密邀请并连接第三方模拟服务"
    )
    connect.add_argument("--invite", required=True)
    connect.add_argument("--message", help="只发送一条消息后退出")
    connect.add_argument("--passphrase-env", default="PSIM_INVITE_PASSPHRASE")
    connect.set_defaults(func=cmd_connect)

    session_parser = subparsers.add_parser("session", help="管理模拟会话")
    session_sub = session_parser.add_subparsers(
        dest="session_command", required=True
    )
    session_list = session_sub.add_parser("list", help="列出会话元数据")
    session_list.add_argument("--server", required=True)
    session_list.add_argument("--admin-token-file")
    session_list.set_defaults(func=cmd_session_list)
    session_delete = session_sub.add_parser("delete", help="删除单个会话")
    session_delete.add_argument("--server", required=True)
    session_delete.add_argument("session_id")
    session_delete.add_argument("--admin-token-file")
    session_delete.set_defaults(func=cmd_session_delete)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except PersonSimError as exc:
        _print_error(exc)
        return int(exc.exit_code)
    except KeyboardInterrupt:
        print("E_INTERRUPTED: 已中断", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"E_IO: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
