"""Direct-identifier scanning and redaction for shareable build artifacts.

The scanner is deliberately conservative and only reports categories/counts.
It never returns the matched values, so warnings and reports can be logged
without echoing private chat content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from person_simulator.errors import PrivacyError

PrivacyMode = Literal["warn", "redact", "block"]
PLACEHOLDER = "[已隐藏]"

_MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d(?:[ -]?\d){8}(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){16}[ -]?[\dXx](?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LANDLINE_RE = re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)")
_BANK_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){15,18}(?!\d)")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

_IDENTIFIER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("id_card", _ID_CARD_RE),
    ("mobile", _MOBILE_RE),
    ("email", _EMAIL_RE),
    ("landline", _LANDLINE_RE),
    ("bank_card", _BANK_CARD_RE),
)


@dataclass(frozen=True)
class PrivacyFinding:
    kind: str
    count: int


@dataclass(frozen=True)
class PrivacyReport:
    findings: tuple[PrivacyFinding, ...] = ()

    @property
    def total(self) -> int:
        return sum(finding.count for finding in self.findings)

    @property
    def clean(self) -> bool:
        return self.total == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "findings": [
                {"kind": finding.kind, "count": finding.count}
                for finding in self.findings
            ],
        }


def _normalized(text: str) -> str:
    return text.translate(_FULLWIDTH_DIGITS)


def scan_text(text: str) -> PrivacyReport:
    """Count direct identifiers by category without echoing matched values."""

    if not text:
        return PrivacyReport()
    normalized = _normalized(text)
    findings: list[PrivacyFinding] = []
    for kind, pattern in _IDENTIFIER_PATTERNS:
        count = sum(1 for _ in pattern.finditer(normalized))
        if count:
            findings.append(PrivacyFinding(kind=kind, count=count))
    return PrivacyReport(findings=tuple(findings))


def _direct_spans(text: str) -> list[tuple[int, int]]:
    normalized = _normalized(text)
    spans: list[tuple[int, int]] = []
    for _, pattern in _IDENTIFIER_PATTERNS:
        spans.extend(
            (match.start(), match.end()) for match in pattern.finditer(normalized)
        )
    return spans


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def redact_text(text: str) -> tuple[str, int]:
    """Replace direct identifiers and return the number of merged spans."""

    spans = _merge_spans(_direct_spans(text))
    if not spans:
        return text, 0

    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(text[cursor:start])
        parts.append(PLACEHOLDER)
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts), len(spans)


def redact_direct_identifiers(text: str) -> tuple[str, int]:
    """Compatibility wrapper used by the runtime output guard."""

    return redact_text(text)


def apply_privacy(
    text: str,
    *,
    mode: PrivacyMode,
    label: str = "导出",
) -> tuple[str, PrivacyReport]:
    """Apply a privacy mode to rendered text.

    ``warn`` leaves the text untouched, ``redact`` replaces direct identifiers,
    and ``block`` raises before the caller writes a shareable artifact.
    """

    if mode not in {"warn", "redact", "block"}:
        raise ValueError(f"unknown privacy mode: {mode}")

    report = scan_text(text)
    if mode == "block" and report.total:
        raise PrivacyError(
            f"{label}包含直接身份信息，已拒绝发布",
            stage="privacy",
            hint="使用 --redact-pii 脱敏，或先清理原始聊天后重试",
        )
    if mode == "redact" and report.total:
        text, _ = redact_text(text)
    return text, report
