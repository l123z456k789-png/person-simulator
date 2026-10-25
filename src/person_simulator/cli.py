"""Command line interface."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

from person_simulator import __version__
from person_simulator.chunking import build_chunk_plan
from person_simulator.config import load_settings
from person_simulator.errors import ConfigError, PersonSimError, PipelineError
from person_simulator.evaluation.prepare import prepare_eval
from person_simulator.evaluation.score import score_eval, write_quality_report
from person_simulator.models import Manifest
from person_simulator.parser import parse_chat
from person_simulator.pipeline import build_run, render_run, resume_run
from person_simulator.providers import build_client
from person_simulator.providers.base import ModelRequest
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


def _add_config_args(parser: argparse.ArgumentParser, *, with_mode: bool = False) -> None:
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
        )
        print("status completed")
        print(f"strategy whole")
        print(f"run_dir {result.run_dir}")
        print(f"system_prompt {result.system_prompt_path}")
        if result.profile_path:
            print(f"person_simulation {result.profile_path}")
        print(f"messages {result.transcript.message_count}")
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
    )
    print(f"status completed")
    print(f"run_dir {result.run_dir}")
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
    if args.max_requests is not None:
        settings.budget.max_requests_per_run = args.max_requests
    if settings.model.mode == "api" and not settings.api_key:
        raise ConfigError("api 模式需要 PSIM_API_KEY", stage="resume")
    result = resume_run(args.run, settings=settings)
    print("status completed")
    print(f"run_dir {result.run_dir}")
    print(f"export {result.export_path}")
    print(f"analysis_status {result.manifest.analysis_status.value}")
    print(f"export_status {result.manifest.export_status.value}")
    if result.system_prompt_path:
        print(f"system_prompt {result.system_prompt_path}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    path = render_run(args.run, args.out)
    text = path.read_text(encoding="utf-8")
    print(f"export {path}")
    print(f"system_prompt {path.parent / 'system_prompt.md'}")
    print(f"characters {len(text)}")
    print(f"bytes {len(text.encode('utf-8'))}")
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
    build.set_defaults(func=cmd_build)

    resume = subparsers.add_parser("resume", help="从检查点恢复运行")
    resume.add_argument("--run", required=True)
    _add_config_args(resume, with_mode=True)
    resume.add_argument("--unlock", action="store_true", help="显式移除已确认陈旧的锁")
    resume.set_defaults(func=cmd_resume)

    render_command = subparsers.add_parser("render", help="从已完成的 run 导出 Markdown")
    render_command.add_argument("--run", required=True)
    render_command.add_argument("--out", required=True)
    render_command.set_defaults(func=cmd_render)

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
