"""Best-effort output checks for third-party simulation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

PLACEHOLDER = "[已隐藏]"
MIN_REPLAY_CHARS = 40
PROMPT_LEAK_WINDOW = 60

_MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d(?:[ -]?\d){8}(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){16}[ -]?[\dXx](?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LANDLINE_RE = re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)")
_BANK_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){15,18}(?!\d)")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_INTERNAL_MARKERS = (
    "person_simulation",
    "system_prompt",
    "persona.json",
    "auto-status",
    "psim_api_key",
    "runtime-persona",
    ".psim",
)
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class GuardResult:
    text: str
    redactions: int
    blocked: bool = False
    reason: str | None = None


def _normalized(text: str) -> str:
    return _WHITESPACE_RE.sub("", text)


def redact_direct_identifiers(text: str) -> tuple[str, int]:
    normalized = text.translate(_FULLWIDTH_DIGITS)
    spans: list[tuple[int, int]] = []
    for pattern in (
        _ID_CARD_RE,
        _MOBILE_RE,
        _EMAIL_RE,
        _LANDLINE_RE,
        _BANK_CARD_RE,
    ):
        spans.extend(
            (match.start(), match.end()) for match in pattern.finditer(normalized)
        )
    if not spans:
        return text, 0

    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        parts.append(text[cursor:start])
        parts.append(PLACEHOLDER)
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts), len(merged)


def find_prompt_leak(text: str, prompt: str) -> bool:
    normalized_prompt = _normalized(prompt)
    normalized_text = _normalized(text)
    if len(normalized_prompt) < PROMPT_LEAK_WINDOW:
        return False
    window = PROMPT_LEAK_WINDOW
    return any(
        normalized_prompt[start : start + window] in normalized_text
        for start in range(len(normalized_prompt) - window + 1)
    )


class OutputGuard:
    def __init__(
        self,
        system_prompt: str,
        *,
        blocked_terms: Iterable[str] = (),
        replay_messages: Iterable[str] = (),
        max_chars: int = 4000,
    ) -> None:
        self.system_prompt = system_prompt
        self.blocked_terms = tuple(
            term for term in blocked_terms if term and term.strip()
        )
        self.replay_messages = tuple(
            message for message in replay_messages if message and message.strip()
        )
        self.max_chars = max_chars
        if self.blocked_terms:
            self._blocked_re = re.compile(
                "|".join(re.escape(term) for term in self.blocked_terms),
                re.IGNORECASE,
            )
        else:
            self._blocked_re = None

    def _blocks_replay(self, text: str) -> bool:
        normalized_text = _normalized(text)
        for message in self.replay_messages:
            normalized_message = _normalized(message)
            if (
                len(normalized_message) >= MIN_REPLAY_CHARS
                and normalized_message in normalized_text
            ):
                return True
        return False

    def check(self, text: str) -> GuardResult:
        if not text or not text.strip():
            return GuardResult("", 0, blocked=True, reason="empty")
        if len(text) > self.max_chars:
            return GuardResult("", 0, blocked=True, reason="too_long")
        if find_prompt_leak(text, self.system_prompt):
            return GuardResult("", 0, blocked=True, reason="prompt_leak")
        lowered = text.casefold()
        if any(marker in lowered for marker in _INTERNAL_MARKERS):
            return GuardResult("", 0, blocked=True, reason="internal_marker")
        if self._blocks_replay(text):
            return GuardResult("", 0, blocked=True, reason="replay")

        redacted, count = redact_direct_identifiers(text)
        if self._blocked_re is not None:
            redacted, substitutions = self._blocked_re.subn(PLACEHOLDER, redacted)
            count += substitutions
        if not redacted.replace(PLACEHOLDER, "").strip():
            return GuardResult("", count, blocked=True, reason="only_redactions")
        return GuardResult(redacted, count)
