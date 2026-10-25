"""Request runner with per-run request cap and attempt accounting."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from person_simulator.errors import PipelineError
from person_simulator.progress import ProgressCallback, ProgressEvent, emit
from person_simulator.providers.base import ModelClient, ModelRequest, ModelResponse
from person_simulator.providers.retry import complete_with_retry


class RequestRunner:
    def __init__(
        self,
        client: ModelClient,
        *,
        max_attempts: int,
        max_requests: int,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.client = client
        self.max_attempts = max_attempts
        self.max_requests = max_requests
        self.sleep = sleep
        self.rng = rng
        self.progress = progress
        self.used = 0

    def call(self, request: ModelRequest) -> ModelResponse:
        if self.used >= self.max_requests:
            raise PipelineError(
                "达到本次运行的请求数上限",
                stage="pipeline",
                task_id=request.task_id,
                hint="保留检查点；提高 budget.max_requests_per_run 或缩小输入后重试",
            )
        emit(
            self.progress,
            ProgressEvent(
                stage="request",
                message="start",
                task_id=request.task_id,
                requests_used=self.used,
            ),
        )
        try:
            response, attempts = complete_with_retry(
                self.client,
                request,
                max_attempts=self.max_attempts,
                sleep=self.sleep,
                rng=self.rng,
            )
        except BaseException:
            emit(
                self.progress,
                ProgressEvent(
                    stage="request",
                    message="failed",
                    task_id=request.task_id,
                    requests_used=self.used,
                ),
            )
            raise
        self.used += attempts
        if self.used > self.max_requests:
            raise PipelineError(
                "请求数超过本次运行上限",
                stage="pipeline",
                task_id=request.task_id,
            )
        emit(
            self.progress,
            ProgressEvent(
                stage="request",
                message="done",
                task_id=request.task_id,
                requests_used=self.used,
            ),
        )
        return response
