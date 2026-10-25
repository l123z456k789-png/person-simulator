"""Bounded retry with exponential backoff and injectable clocks."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from person_simulator.errors import ProviderUnavailable, RateLimitError, TransportError
from person_simulator.providers.base import ModelClient, ModelRequest, ModelResponse

RETRYABLE = (TransportError, RateLimitError, ProviderUnavailable)


def complete_with_retry(
    client: ModelClient,
    request: ModelRequest,
    *,
    max_attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    max_wait: float = 30.0,
) -> tuple[ModelResponse, int]:
    generator = rng or random.Random()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return client.complete(request), attempt
        except RETRYABLE as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise
            retry_after = getattr(exc, "retry_after", None)
            if isinstance(retry_after, (int, float)) and retry_after >= 0:
                delay = min(float(retry_after), max_wait)
            else:
                delay = min(max_wait, float(2 ** (attempt - 1)) + generator.uniform(0.0, 0.25))
            sleep(delay)
    raise last_error  # type: ignore[misc]  # pragma: no cover
