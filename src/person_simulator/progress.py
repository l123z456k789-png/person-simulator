"""Optional, content-free progress events for long-running builds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    message: str
    current: int | None = None
    total: int | None = None
    task_id: str | None = None
    requests_used: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "message": self.message,
            "current": self.current,
            "total": self.total,
            "task_id": self.task_id,
            "requests_used": self.requests_used,
        }


ProgressCallback = Callable[[ProgressEvent], None]


def emit(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    if callback is not None:
        callback(event)
