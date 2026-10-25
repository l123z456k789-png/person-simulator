"""Convert one specific WeChat Markdown export format to person-simulator input.

This is a local helper for a known export shape, not a general WeChat parser.
It never prints message bodies.

Input shape:
    ## 2025-06-10
    **[18:51:34] 翙**
    message text
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DAY_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*$")
MSG_RE = re.compile(r"^\*\*\[(\d{2}:\d{2}:\d{2})\]\s+([^*]+?)\*\*\s*$")


@dataclass(frozen=True)
class ExportMessage:
    day: str
    time: str
    speaker: str
    text: str


def parse_export(text: str) -> tuple[list[ExportMessage], Counter[str], int]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    messages: list[ExportMessage] = []
    labels: Counter[str] = Counter()
    empty = 0
    current_day: str | None = None
    current: dict[str, object] | None = None

    def flush() -> None:
        nonlocal current, empty
        if current is None:
            return
        body = "\n".join(current["body"]).strip("\n")  # type: ignore[arg-type]
        if not body.strip():
            empty += 1
        else:
            speaker = str(current["speaker"])
            labels[speaker] += 1
            messages.append(
                ExportMessage(
                    day=str(current["day"]),
                    time=str(current["time"]),
                    speaker=speaker,
                    text=body,
                )
            )
        current = None

    for line in lines:
        day_match = DAY_RE.match(line)
        if day_match:
            flush()
            current_day = day_match.group(1)
            continue
        message_match = MSG_RE.match(line)
        if message_match:
            flush()
            current = {
                "day": current_day or "",
                "time": message_match.group(1),
                "speaker": message_match.group(2).strip(),
                "body": [],
            }
            continue
        if current is not None:
            if line.strip() == "":
                if current["body"]:  # type: ignore[truthiness]
                    flush()
            else:
                current["body"].append(line)  # type: ignore[union-attr]
    flush()
    return messages, labels, empty


def serialize(messages: list[ExportMessage], speaker_a: str, speaker_b: str) -> str:
    blocks: list[str] = []
    for message in messages:
        if message.speaker not in (speaker_a, speaker_b):
            continue
        body_lines = message.text.split("\n")
        header = f"[{message.day}T{message.time}] {message.speaker}: {body_lines[0]}"
        lines = [header]
        lines.extend(f"  {line}" for line in body_lines[1:])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def convert(
    source: str | Path,
    output: str | Path,
    *,
    speaker_a: str,
    speaker_b: str,
) -> dict[str, object]:
    source_path = Path(source)
    raw = source_path.read_bytes()
    text = raw.decode("utf-8-sig")
    messages, labels, empty = parse_export(text)
    output_text = serialize(messages, speaker_a, speaker_b)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_text, encoding="utf-8")
    included = Counter(
        message.speaker for message in messages if message.speaker in (speaker_a, speaker_b)
    )
    skipped = {
        label: count
        for label, count in labels.items()
        if label not in (speaker_a, speaker_b)
    }
    summary = {
        "source": str(source_path.resolve()),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "output": str(output_path.resolve()),
        "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
        "messages_total": len(messages),
        "messages_included": sum(included.values()),
        "messages_by_speaker": dict(included),
        "skipped_by_speaker": skipped,
        "empty_bodies": empty,
        "speaker_a": speaker_a,
        "speaker_b": speaker_b,
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert a known WeChat Markdown export.")
    parser.add_argument("source")
    parser.add_argument("--out", default="data/chat.txt")
    parser.add_argument("--speaker-a", required=True)
    parser.add_argument("--speaker-b", required=True)
    args = parser.parse_args(argv)
    summary = convert(
        args.source,
        args.out,
        speaker_a=args.speaker_a,
        speaker_b=args.speaker_b,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["messages_included"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
