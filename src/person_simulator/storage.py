"""Atomic run storage, checkpoints and a single-run lock."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel

from person_simulator.errors import StorageError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def analysis_filename(task_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)[:80]
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:10]
    return f"{safe}-{digest}.json"


def make_run_id(target: str, source_hash: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "-", target).strip("-").lower() or "target"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"run-{stamp}-{safe}-{source_hash[:6]}"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class RunStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._locked = False

    @classmethod
    def create(cls, out_root: Path, run_id: str) -> "RunStore":
        out_root = Path(out_root)
        try:
            out_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError("无法创建输出目录", stage="storage", hint=str(out_root)) from exc
        candidate = out_root / run_id
        suffix = 2
        while candidate.exists():
            candidate = out_root / f"{run_id}-{suffix}"
            suffix += 1
        try:
            candidate.mkdir(parents=False)
        except OSError as exc:
            raise StorageError("无法创建运行目录", stage="storage", hint=str(candidate)) from exc
        store = cls(candidate)
        store.acquire_lock()
        for child in ("analysis",):
            (store.path / child).mkdir(exist_ok=True)
        _best_effort_permissions(store.path, 0o700)
        return store

    @classmethod
    def open(cls, path: Path) -> "RunStore":
        path = Path(path)
        if not (path / "manifest.json").is_file():
            raise StorageError("运行目录缺少 manifest.json", stage="storage", hint=str(path))
        return cls(path)

    @property
    def lock_path(self) -> Path:
        return self.path / ".lock"

    def acquire_lock(self) -> None:
        payload = json.dumps(
            {"pid": os.getpid(), "created_at": utcnow().isoformat(), "run": str(self.path)},
            ensure_ascii=False,
        )
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            detail = "锁文件已存在"
            try:
                existing = json.loads(self.lock_path.read_text(encoding="utf-8"))
                detail = f"锁文件已存在（pid={existing.get('pid')}, created_at={existing.get('created_at')}）"
            except (OSError, ValueError):
                pass
            raise StorageError(
                f"运行目录已被占用：{detail}",
                stage="storage",
                hint="确认没有其他进程运行；陈旧锁使用 resume --run <dir> --unlock 显式解锁",
            ) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        self._locked = True

    def release_lock(self) -> None:
        if self._locked:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise StorageError("无法释放运行锁", stage="storage", hint=str(self.lock_path)) from exc
            self._locked = False

    def unlock_stale(self) -> str:
        if not self.lock_path.exists():
            return "没有锁文件"
        try:
            existing = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StorageError(
                "锁文件损坏，拒绝自动删除",
                stage="storage",
                hint="人工检查 .lock 后再决定",
            ) from exc
        pid = int(existing.get("pid", 0))
        created = str(existing.get("created_at", ""))
        try:
            created_at = datetime.fromisoformat(created)
            age = (utcnow() - created_at).total_seconds()
        except ValueError:
            age = 0.0
        if _pid_alive(pid) and age < 86400:
            raise StorageError(
                f"锁仍被活动进程持有（pid={pid}）",
                stage="storage",
                hint="不要删除正在运行的锁",
            )
        self.lock_path.unlink()
        return f"已移除陈旧锁（pid={pid}, age={int(age)}s）"

    def _path(self, relative: str | Path) -> Path:
        target = (self.path / relative).resolve()
        root = self.path.resolve()
        if root != target and root not in target.parents:
            raise StorageError("拒绝写入运行目录之外的路径", stage="storage")
        return target

    def write_json(self, relative: str | Path, value: Any, *, private: bool = True) -> Path:
        target = self._path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, BaseModel):
            data = value.model_dump(mode="json")
        else:
            data = value
        text = json.dumps(data, ensure_ascii=False, indent=2)
        return self._atomic_text(target, text + "\n", private=private)

    def write_jsonl(
        self, relative: str | Path, rows: Iterable[Any], *, private: bool = True
    ) -> Path:
        target = self._path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for row in rows:
            data = row.model_dump(mode="json") if isinstance(row, BaseModel) else row
            lines.append(json.dumps(data, ensure_ascii=False))
        return self._atomic_text(target, "\n".join(lines) + ("\n" if lines else ""), private=private)

    def write_text(self, relative: str | Path, text: str, *, private: bool = False) -> Path:
        target = self._path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        return self._atomic_text(target, text, private=private)

    def _atomic_text(self, target: Path, text: str, *, private: bool) -> Path:
        temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageError("原子写入失败", stage="storage", hint=str(target)) from exc
        if private:
            _best_effort_permissions(target, 0o600)
        return target

    def read_json(self, relative: str | Path) -> Any:
        target = self._path(relative)
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise StorageError("运行文件不存在", stage="storage", hint=str(target)) from exc
        except (OSError, ValueError) as exc:
            raise StorageError("运行文件损坏", stage="storage", hint=str(target)) from exc

    def read_jsonl(self, relative: str | Path) -> list[Any]:
        target = self._path(relative)
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError as exc:
            raise StorageError("运行文件不存在", stage="storage", hint=str(target)) from exc
        rows = []
        for line in lines:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    raise StorageError("JSONL 行损坏", stage="storage", hint=str(target)) from exc
        return rows

    def exists(self, relative: str | Path) -> bool:
        return self._path(relative).exists()


def _best_effort_permissions(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass
