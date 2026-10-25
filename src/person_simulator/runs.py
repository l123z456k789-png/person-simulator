"""Read-only run inventory plus explicit delete/purge operations."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from person_simulator.errors import StorageError
from person_simulator.storage import RunStore

_KNOWN_FILES = (
    "manifest.json",
    "messages.jsonl",
    "chunks.jsonl",
    "persona.json",
    "person_simulation.md",
    "system_prompt.md",
    "build_report.md",
)


@dataclass(frozen=True)
class RunSummary:
    path: Path
    run_id: str
    strategy: str
    status: str
    target: str | None
    is_mock: bool
    created_at: str | None
    updated_at: str | None
    size_bytes: int
    locked: bool
    lock_pid: int | None
    has_export: bool
    has_persona: bool
    has_messages: bool
    limited: bool = False
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "path": str(self.path),
            "strategy": self.strategy,
            "status": self.status,
            "target": self.target,
            "is_mock": self.is_mock,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "size_bytes": self.size_bytes,
            "locked": self.locked,
            "lock_pid": self.lock_pid,
            "has_export": self.has_export,
            "has_persona": self.has_persona,
            "has_messages": self.has_messages,
            "limited": self.limited,
            "error": self.error,
        }


@dataclass(frozen=True)
class RunDetail:
    summary: RunSummary
    task_counts: dict[str, int] = field(default_factory=dict)
    files: dict[str, bool] = field(default_factory=dict)
    manifest_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary.as_dict(),
            "task_counts": dict(self.task_counts),
            "files": dict(self.files),
            "manifest_error": self.manifest_error,
        }


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    checker = getattr(path, "is_junction", None)
    if callable(checker):
        try:
            return bool(checker())
        except OSError:
            return True
    return False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StorageError("run 缺少 manifest.json", stage="runs", hint=str(path)) from exc
    except (OSError, ValueError) as exc:
        raise StorageError("run 的 manifest.json 损坏", stage="runs", hint=str(path)) from exc
    if not isinstance(value, dict):
        raise StorageError("run 的 manifest.json 顶层不是对象", stage="runs", hint=str(path))
    return value


def _lock_info(path: Path) -> tuple[bool, int | None]:
    lock = path / ".lock"
    if not lock.exists():
        return False, None
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        pid = int(data.get("pid", 0))
        return True, pid if pid > 0 else None
    except (OSError, ValueError, TypeError):
        return True, None


def _directory_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _summary(path: Path) -> RunSummary:
    locked, lock_pid = _lock_info(path)
    has_export = (path / "person_simulation.md").is_file() or (
        path / "system_prompt.md"
    ).is_file()
    has_persona = (path / "persona.json").is_file()
    has_messages = (path / "messages.jsonl").is_file()
    try:
        data = _read_json(path / "manifest.json")
    except StorageError as exc:
        return RunSummary(
            path=path,
            run_id=path.name,
            strategy="unknown",
            status="invalid",
            target=None,
            is_mock=False,
            created_at=None,
            updated_at=None,
            size_bytes=_directory_size(path),
            locked=locked,
            lock_pid=lock_pid,
            has_export=has_export,
            has_persona=has_persona,
            has_messages=has_messages,
            error=exc.message,
        )

    whole = data.get("strategy") == "whole" or data.get("schema_version") == "whole-1.0"
    strategy = "whole" if whole else "evidence"
    status = str(
        data.get("status") if whole else data.get("analysis_status", "unknown")
    )
    budget = data.get("budget")
    limited = bool(
        data.get("limited") is True
        or (
            isinstance(budget, dict)
            and budget.get("limit_messages") is not None
            and isinstance(budget.get("source_message_count"), int)
            and isinstance(budget.get("analyzed_message_count"), int)
            and budget["analyzed_message_count"] < budget["source_message_count"]
        )
    )
    return RunSummary(
        path=path,
        run_id=str(data.get("run_id") or path.name),
        strategy=strategy,
        status=status,
        target=data.get("target") if isinstance(data.get("target"), str) else None,
        is_mock=bool(data.get("is_mock", False)),
        created_at=_as_text(data.get("created_at")),
        updated_at=_as_text(data.get("updated_at")),
        size_bytes=_directory_size(path),
        locked=locked,
        lock_pid=lock_pid,
        has_export=has_export,
        has_persona=has_persona,
        has_messages=has_messages,
        limited=limited,
    )


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def list_runs(root: str | Path = "runs") -> list[RunSummary]:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        return []
    if not root_path.is_dir() or _is_link(root_path):
        raise StorageError("run 根目录不是普通目录", stage="runs", hint=str(root_path))
    summaries: list[RunSummary] = []
    for child in root_path.iterdir():
        if _is_link(child) or not child.is_dir():
            continue
        if not (child / "manifest.json").is_file():
            continue
        summaries.append(_summary(child))
    summaries.sort(key=lambda item: (item.created_at or "", item.run_id), reverse=True)
    return summaries


def _resolve_run(run: str | Path, *, root: str | Path) -> Path:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists() or not root_path.is_dir() or _is_link(root_path):
        raise StorageError("run 根目录无效", stage="runs", hint=str(root_path))
    candidate = Path(run).expanduser()
    if not candidate.is_absolute():
        candidate = root_path / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise StorageError("run 不存在", stage="runs", hint=str(candidate)) from exc
    if _is_link(candidate) or _is_link(resolved):
        raise StorageError("拒绝操作符号链接/junction run", stage="runs", hint=str(candidate))
    if not resolved.is_dir():
        raise StorageError("run 不是目录", stage="runs", hint=str(candidate))
    try:
        inside = os.path.commonpath([str(resolved), str(root_path)]) == str(root_path)
    except ValueError as exc:
        raise StorageError("run 不在指定根目录内", stage="runs", hint=str(candidate)) from exc
    if not inside or resolved == root_path:
        raise StorageError("run 不在指定根目录内", stage="runs", hint=str(candidate))
    if not (resolved / "manifest.json").is_file():
        raise StorageError("run 缺少 manifest.json", stage="runs", hint=str(resolved))
    return resolved


def inspect_run(run: str | Path, *, root: str | Path = "runs") -> RunDetail:
    path = _resolve_run(run, root=root)
    summary = _summary(path)
    files = {name: (path / name).is_file() for name in _KNOWN_FILES}
    task_counts: dict[str, int] = {}
    manifest_error: str | None = None
    try:
        data = _read_json(path / "manifest.json")
        tasks = data.get("tasks")
        if isinstance(tasks, dict):
            for task in tasks.values():
                if isinstance(task, dict):
                    status = str(task.get("status", "unknown"))
                    task_counts[status] = task_counts.get(status, 0) + 1
    except StorageError as exc:
        manifest_error = exc.message
    return RunDetail(
        summary=summary,
        task_counts=task_counts,
        files=files,
        manifest_error=manifest_error,
    )


def _lock_pid_for_delete(path: Path) -> None:
    lock = path / ".lock"
    if not lock.exists():
        return
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        pid = int(data.get("pid", 0))
    except (OSError, ValueError, TypeError):
        pid = 0
    raise StorageError(
        f"run 仍被锁文件占用（pid={pid or 'unknown'}）",
        stage="runs",
        hint="确认没有进程在使用；陈旧锁使用 --force 清理",
    )


def delete_run(
    run: str | Path,
    *,
    root: str | Path = "runs",
    force: bool = False,
) -> None:
    path = _resolve_run(run, root=root)
    if (path / ".lock").exists():
        if not force:
            _lock_pid_for_delete(path)
        try:
            store = RunStore.open(path)
            store.unlock_stale()
        except StorageError:
            raise
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise StorageError("无法删除 run", stage="runs", hint=str(path)) from exc


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def purge_runs(
    root: str | Path = "runs",
    *,
    statuses: Iterable[str] = (),
    older_than_days: int | None = None,
    all_runs: bool = False,
    apply: bool = False,
    force: bool = False,
) -> list[RunSummary]:
    wanted = tuple(statuses)
    if not wanted and older_than_days is None and not all_runs:
        raise StorageError(
            "purge 需要 --status、--older-than-days 或 --all 之一",
            stage="runs",
            hint="先用 dry-run 查看候选，再显式 apply",
        )
    if older_than_days is not None and older_than_days < 0:
        raise StorageError("older-than-days 不能为负数", stage="runs")
    now = datetime.now(timezone.utc)
    selected: list[RunSummary] = []
    for summary in list_runs(root):
        if not all_runs and wanted and summary.status not in wanted:
            continue
        if older_than_days is not None:
            created = _parse_time(summary.created_at)
            if created is None or (now - created).days < older_than_days:
                continue
        selected.append(summary)
    if not apply:
        return selected
    if not force and any(summary.locked for summary in selected):
        raise StorageError(
            "选中 run 中存在锁文件，拒绝批量删除",
            stage="runs",
            hint="先用 runs status 确认；只对确认陈旧的锁使用 --force",
        )
    deleted: list[RunSummary] = []
    for summary in selected:
        delete_run(summary.path, root=root, force=force)
        deleted.append(summary)
    return deleted
