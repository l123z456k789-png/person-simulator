"""Whole-chat transcript serialization and token budgeting."""

from __future__ import annotations

from dataclasses import dataclass

from person_simulator.budget import PACKAGING_MARGIN, estimate_tokens
from person_simulator.models import Message


@dataclass(frozen=True)
class Transcript:
    text: str
    message_count: int
    char_count: int
    estimated_tokens: int
    first_message_id: str | None
    last_message_id: str | None
    limited: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "message_count": self.message_count,
            "char_count": self.char_count,
            "estimated_tokens": self.estimated_tokens,
            "estimated_method": "min(ceil(utf8_bytes*1.25), chars+1) + actual usage after call (heuristic, not a tokenizer)",
            "first_message_id": self.first_message_id,
            "last_message_id": self.last_message_id,
            "limited": self.limited,
        }


def render_message(message: Message) -> str:
    timestamp = f"{message.timestamp.isoformat(sep=' ')} " if message.timestamp else ""
    lines = message.text.split("\n")
    head = f"[{message.id}] {timestamp}{message.speaker}: {lines[0]}"
    if len(lines) == 1:
        return head
    return "\n".join([head, *(f"  {line}" for line in lines[1:])])


def serialize_transcript(
    messages: list[Message],
    *,
    limit: int | None = None,
) -> Transcript:
    selected = messages[:limit] if limit is not None else messages
    text = "\n".join(render_message(message) for message in selected)
    byte_heuristic = estimate_tokens(text)
    # Chinese chat is usually <= 1 token per character; cap the byte
    # heuristic so a 1M-context model is not rejected by a 3x overestimate.
    calibrated = min(byte_heuristic, len(text) + 1) if text else 0
    return Transcript(
        text=text,
        message_count=len(selected),
        char_count=len(text),
        estimated_tokens=calibrated,
        first_message_id=selected[0].id if selected else None,
        last_message_id=selected[-1].id if selected else None,
        limited=limit is not None and limit < len(messages),
    )


def transcript_budget(
    transcript: Transcript,
    *,
    system: str,
    output_limit: int,
    safety_margin: int,
) -> int:
    """Conservative request estimate before the call."""
    return estimate_tokens(system) + transcript.estimated_tokens + output_limit + safety_margin
