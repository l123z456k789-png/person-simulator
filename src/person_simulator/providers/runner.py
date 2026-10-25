"""Request runner with per-run request cap and attempt accounting."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from person_simulator.errors import PipelineError
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
    ) -> None:
        self.client = client
        self.max_attempts = max_attempts
        self.max_requests = max_requests
        self.sleep = sleep
        self.rng = rng
        self.used = 0

    def call(self, request: ModelRequest) -> ModelResponse:
        if self.used >= self.max_requests:
            raise PipelineError(
                "达到本次运行的请求数上限",
                stage="pipeline",
                task_id=request.task_id,
                hint="保留检查点；提高 budget.max_requests_per_run 或缩小输入后重试",
            )
        response, attempts = complete_with_retry(
            self.client,
            request,
            max_attempts=self.max_attempts,
            sleep=self.sleep,
            rng=self.rng,
        )
        self.used += attempts
        if self.used > self.max_requests:
            raise PipelineError(
                "请求数超过本次运行上限",
                stage="pipeline",
                task_id=request.task_id,
            )
        return response
