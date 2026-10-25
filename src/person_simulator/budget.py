"""Conservative token-budget heuristics.

This is deliberately not a model tokenizer. It over-estimates with UTF-8
bytes * 1.25 plus a fixed packaging margin.
"""

from __future__ import annotations

import math

from person_simulator.errors import ConfigError

PACKAGING_MARGIN = 512


def estimate_tokens(text: str) -> int:
    """Conservative estimate for one text field."""
    if not text:
        return 0
    return math.ceil(len(text.encode("utf-8")) * 1.25)


def estimate_request_tokens(system: str, user: str, schema: str = "") -> int:
    """Estimate a serialized request, including the packaging margin."""
    return (
        PACKAGING_MARGIN
        + estimate_tokens(system)
        + estimate_tokens(user)
        + estimate_tokens(schema)
    )


def safety_margin(context_window: int) -> int:
    return max(2048, math.ceil(context_window * 0.1))


def validate_context_budget(
    estimated_input: int,
    max_output_tokens: int,
    context_window: int,
    *,
    label: str = "request",
) -> None:
    required = estimated_input + max_output_tokens + safety_margin(context_window)
    if required > context_window:
        raise ConfigError(
            f"{label} 超出上下文预算：需要 {required}，context_window={context_window}",
            stage="budget",
            hint="减小 chunk_input_budget 或 max_output_tokens，或配置真实 context_window",
        )
