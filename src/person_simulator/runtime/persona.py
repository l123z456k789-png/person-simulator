"""Strict loading of completed runs into the runtime persona contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from person_simulator import __version__
from person_simulator.errors import (
    RunHashError,
    RunIncompleteError,
    RunNotFoundError,
    RunVersionError,
)
from person_simulator.models import (
    AnalysisStatus,
    ExportStatus,
    Manifest,
    Persona,
)
from person_simulator.runtime.models import (
    Audience,
    LoadedPersona,
    RuntimePersona,
)
from person_simulator.runtime.prompts import build_runtime_prompt
from person_simulator.storage import utcnow

_SUPPORTED_EVIDENCE_SCHEMA = "1.0"
_SUPPORTED_WHOLE_SCHEMA = "whole-1.0"
_SUPPORTED_PACKAGE_MINORS = {("0", "1"), ("0", "2")}
_EXTERNAL_MARKERS = ("```include", "!http://", "!https://")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunIncompleteError(
            "run 缺少必要文件", stage="runtime", hint=str(path)
        ) from exc
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RunIncompleteError(
            "run 文件损坏或不是有效 UTF-8/JSON", stage="runtime", hint=str(path)
        ) from exc


def _read_prompt(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RunIncompleteError(
            "run 缺少 system_prompt.md", stage="runtime", hint=str(path)
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise RunIncompleteError(
            "system_prompt.md 不可读或不是 UTF-8", stage="runtime", hint=str(path)
        ) from exc
    if not text.strip():
        raise RunIncompleteError(
            "system_prompt.md 为空", stage="runtime", hint=str(path)
        )
    lowered = text.lower()
    for marker in _EXTERNAL_MARKERS:
        if marker in lowered:
            raise RunIncompleteError(
                "system_prompt.md 包含外部依赖标记", stage="runtime", hint=str(path)
            )
    return text


def _read_message_texts(path: Path) -> tuple[str, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ()
    except (OSError, UnicodeDecodeError) as exc:
        raise RunIncompleteError(
            "messages.jsonl 不可读或不是 UTF-8", stage="runtime", hint=str(path)
        ) from exc

    texts: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise RunIncompleteError(
                "messages.jsonl 行损坏", stage="runtime", hint=str(path)
            ) from exc
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            raise RunIncompleteError(
                "messages.jsonl 缺少 text 字段", stage="runtime", hint=str(path)
            )
        if row["text"].strip():
            texts.append(row["text"])
    return tuple(texts)


def _supported_package_version(value: str) -> bool:
    parts = value.split(".")
    return len(parts) >= 2 and (parts[0], parts[1]) in _SUPPORTED_PACKAGE_MINORS


def _load_evidence(
    run_dir: Path,
    data: dict[str, Any],
    audience: Audience,
) -> LoadedPersona:
    raw_schema = str(data.get("schema_version", _SUPPORTED_EVIDENCE_SCHEMA))
    if raw_schema != _SUPPORTED_EVIDENCE_SCHEMA:
        raise RunVersionError(
            "不支持的 evidence manifest schema",
            stage="runtime",
            hint=f"schema_version={raw_schema}",
        )
    try:
        manifest = Manifest.model_validate(data)
    except ValidationError as exc:
        raise RunIncompleteError(
            "manifest.json 不符合 evidence 契约", stage="runtime"
        ) from exc

    if not _supported_package_version(manifest.package_version):
        raise RunVersionError(
            "不支持的 run package_version",
            stage="runtime",
            hint=f"package_version={manifest.package_version}",
        )
    if (
        manifest.analysis_status != AnalysisStatus.COMPLETE
        or manifest.export_status != ExportStatus.COMPLETE
    ):
        raise RunIncompleteError(
            "run 分析或导出未完成，拒绝加载",
            stage="runtime",
            hint=f"analysis={manifest.analysis_status.value}, export={manifest.export_status.value}",
        )
    if manifest.coverage is None or not manifest.coverage.complete:
        raise RunIncompleteError("run 覆盖不完整，拒绝加载", stage="runtime")

    try:
        persona = Persona.model_validate(_read_json(run_dir / "persona.json"))
    except ValidationError as exc:
        raise RunIncompleteError(
            "persona.json 不符合契约", stage="runtime"
        ) from exc
    if not persona.coverage.complete or persona.coverage.ratio < 1.0:
        raise RunIncompleteError("persona 覆盖不完整，拒绝加载", stage="runtime")
    if persona.source_hash != manifest.source_hash:
        raise RunHashError(
            "manifest 与 persona 的 source_hash 不一致", stage="runtime"
        )
    if persona.target != manifest.target or persona.interlocutor != manifest.interlocutor:
        raise RunHashError(
            "manifest 与 persona 的身份不一致", stage="runtime"
        )

    original = _read_prompt(run_dir / "system_prompt.md")
    replay_messages = _read_message_texts(run_dir / "messages.jsonl")
    if not replay_messages:
        raise RunIncompleteError(
            "evidence run 缺少 messages.jsonl 文本", stage="runtime"
        )
    composed = build_runtime_prompt(original, audience)
    return LoadedPersona(
        persona=RuntimePersona(
            run_id=manifest.run_id,
            strategy="evidence",
            package_version=manifest.package_version,
            prompt_version=manifest.prompt_version,
            source_hash=manifest.source_hash,
            target=manifest.target,
            interlocutor=manifest.interlocutor,
            system_prompt=composed,
            system_prompt_sha256=hashlib.sha256(composed.encode("utf-8")).hexdigest(),
            original_system_prompt_sha256=hashlib.sha256(
                original.encode("utf-8")
            ).hexdigest(),
            is_mock=manifest.is_mock,
            audience=audience,
            replay_guard="full",
            created_at=utcnow(),
        ),
        replay_messages=replay_messages,
    )


def _load_whole(
    run_dir: Path,
    data: dict[str, Any],
    audience: Audience,
) -> LoadedPersona:
    raw_schema = str(data.get("schema_version", ""))
    if raw_schema != _SUPPORTED_WHOLE_SCHEMA:
        raise RunVersionError(
            "不支持的 whole manifest schema",
            stage="runtime",
            hint=f"schema_version={raw_schema or 'missing'}",
        )
    if data.get("strategy") != "whole":
        raise RunIncompleteError("manifest 不是 whole strategy", stage="runtime")
    if data.get("status") != "complete":
        raise RunIncompleteError(
            "whole run 未完成，拒绝加载",
            stage="runtime",
            hint=f"status={data.get('status')!r}",
        )
    for key in ("source_hash", "target", "interlocutor"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise RunIncompleteError(
                f"whole manifest 缺少 {key}", stage="runtime"
            )

    original = _read_prompt(run_dir / "system_prompt.md")
    replay_messages = _read_message_texts(run_dir / "messages.jsonl")
    composed = build_runtime_prompt(original, audience)
    run_id = str(data.get("run_id") or run_dir.name)
    return LoadedPersona(
        persona=RuntimePersona(
            run_id=run_id,
            strategy="whole",
            package_version=str(data.get("package_version") or __version__),
            prompt_version=str(data.get("prompt_version") or _SUPPORTED_WHOLE_SCHEMA),
            source_hash=str(data["source_hash"]),
            target=str(data["target"]),
            interlocutor=str(data["interlocutor"]),
            system_prompt=composed,
            system_prompt_sha256=hashlib.sha256(composed.encode("utf-8")).hexdigest(),
            original_system_prompt_sha256=hashlib.sha256(
                original.encode("utf-8")
            ).hexdigest(),
            is_mock=bool(data.get("is_mock", False)),
            audience=audience,
            replay_guard="full" if replay_messages else "prompt_only",
            created_at=utcnow(),
        ),
        replay_messages=replay_messages,
    )


def load_runtime_persona(
    run_dir: str | Path,
    *,
    audience: Audience | str = Audience.GUEST,
) -> LoadedPersona:
    """Load a completed run, refusing anything that is not safe to simulate."""

    try:
        chosen_audience = audience if isinstance(audience, Audience) else Audience(audience)
    except ValueError as exc:
        raise RunVersionError(
            "未知的 audience", stage="runtime", hint=str(audience)
        ) from exc

    path = Path(run_dir).expanduser()
    if not path.exists():
        raise RunNotFoundError(
            "run 目录不存在", stage="runtime", hint=str(path)
        )
    if path.is_symlink() or not path.is_dir():
        raise RunNotFoundError(
            "run 路径不是普通目录", stage="runtime", hint=str(path)
        )

    data = _read_json(path / "manifest.json")
    if not isinstance(data, dict):
        raise RunIncompleteError("manifest.json 顶层不是对象", stage="runtime")

    if data.get("strategy") == "whole" or data.get("schema_version") == _SUPPORTED_WHOLE_SCHEMA:
        return _load_whole(path, data, chosen_audience)
    return _load_evidence(path, data, chosen_audience)
