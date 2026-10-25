from __future__ import annotations

import math

import pytest

from person_simulator.budget import (
    PACKAGING_MARGIN,
    estimate_request_tokens,
    estimate_tokens,
    safety_margin,
    validate_context_budget,
)
from person_simulator.errors import ConfigError


def test_estimate_uses_bytes_and_ceiling():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abc") == math.ceil(3 * 1.25)
    assert estimate_tokens("中文") == math.ceil(6 * 1.25)


def test_request_estimate_has_packaging_margin():
    assert estimate_request_tokens("a", "b") == PACKAGING_MARGIN + estimate_tokens("a") + estimate_tokens("b")


def test_safety_margin_is_max_of_2048_and_ten_percent():
    assert safety_margin(1000) == 2048
    assert safety_margin(100000) == 10000


def test_context_budget_rejects_overflow():
    with pytest.raises(ConfigError):
        validate_context_budget(30000, 4096, 32768)


def test_context_budget_accepts_fit():
    validate_context_budget(1000, 4096, 32768)
