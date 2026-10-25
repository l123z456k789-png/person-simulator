"""Strict parser for cleaned two-person chat text."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from person_simulator.errors import InputError
from person_simulator.models import Message

HEADER_RE = re.compile(
    r"^(?:\[(?P<ts>[^\]\r\n]+)\]\s+)?(?P<label>[^:：\[\]\r\n]+)[:：](?P<rest>.*)$"
)
SESSION_GAP = timedelta(minutes=30)
FORBIDDEN_LABEL_CHARS = (":", "：", "[", "]", "\n", "\r")


@dataclass
class ParsedChat:
    messages: list[Message]
    warnings: list[str] = field(default_factory=list)
    source_hash: str = ""
    speaker_a: str = "A"
    speaker_b: str = "B"

    @property
    def labels(self) -> tuple[str, str]:
        return self.speaker_a, self.speaker_b


def validate_labels(speaker_a: str, speaker_b: str, target: str) -> tuple[str, str, str]:
    a = speaker_a.strip()
    b = speaker_b.strip()
    t = target.strip()
    for name, label in (("speaker-a", a), ("speaker-b", b)):
        if not label:
            raise InputError(f"{name} 不能为空", stage="input", hint="提供非空说话人标签")
        if any(ch in label for ch in FORBIDDEN_LABEL_CHARS):
            raise InputError(
                f"{name} 不能包含冒号、方括号或换行",
                stage="input",
                hint="使用简短标签，例如 小明",
            )
    if a == b:
        raise InputError("两个说话人标签必须不同", stage="input", hint="分别设置 --speaker-a 和 --speaker-b")
    if t not in (a, b):
        raise InputError(
            "target 必须精确匹配 speaker-a 或 speaker-b",
            stage="input",
            hint="检查 --target 的大小写与空格",
        )
    return a, b, t


def _line_of_byte_offset(raw: bytes, offset: int) -> int:
    return raw[:offset].count(b"\n") + 1


def _parse_timestamp(raw: str, line_no: int) -> datetime:
    value = raw.strip()
    if not value or ("T" not in value and " " not in value):
        raise InputError(
            "时间戳不是带时间的 ISO8601",
            stage="input",
            hint=f"第 {line_no} 行使用 [YYYY-MM-DDTHH:MM:SS+08:00] 格式",
        )
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputError(
            "时间戳不是合法 ISO8601",
            stage="input",
            hint=f"第 {line_no} 行检查日期、时间与时区",
        ) from exc


def _comparable(one: datetime, other: datetime) -> bool:
    return (one.tzinfo is None) == (other.tzinfo is None)


def parse_chat(
    path: str | Path,
    speaker_a: str = "A",
    speaker_b: str = "B",
    *,
    target: str | None = None,
) -> ParsedChat:
    """Parse a chat file. Raises InputError with a line number, never body text."""

    path = Path(path)
    a, b, _ = validate_labels(speaker_a, speaker_b, target if target is not None else speaker_a)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise InputError("输入文件不存在", stage="input", hint=str(path)) from exc
    except IsADirectoryError as exc:
        raise InputError("输入路径是目录，不是文件", stage="input", hint=str(path)) from exc
    except OSError as exc:
        raise InputError("输入文件不可读", stage="input", hint=str(path)) from exc

    if not raw.strip():
        raise InputError("输入文件为空", stage="input", hint="提供 UTF-8 文本聊天")
    if b"\x00" in raw:
        raise InputError("输入包含 NUL 字符", stage="input", hint="移除二进制内容后重试")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError(
            "输入不是有效 UTF-8",
            stage="input",
            hint=f"从第 {_line_of_byte_offset(raw, exc.start)} 行附近检查编码",
        ) from exc

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    source_hash = hashlib.sha256(raw).hexdigest()

    allowed = {a, b}
    warnings: list[str] = []
    messages: list[Message] = []

    current: dict[str, object] | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        body = str(current["text"])
        if body.strip() == "":
            start = int(current["line_start"])
            end = int(current["line_end"])
            raise InputError(
                "消息正文为空",
                stage="input",
                hint=f"第 {start}-{end} 行补充正文或删除该消息头",
            )
        index = len(messages)
        messages.append(
            Message(
                id=f"m{index + 1:06d}",
                index=index,
                speaker=str(current["speaker"]),
                text=body,
                timestamp=current["timestamp"],  # type: ignore[arg-type]
                line_start=int(current["line_start"]),
                line_end=int(current["line_end"]),
                session_id="",
            )
        )
        current = None

    for line_no, line in enumerate(lines, start=1):
        if line.startswith("  "):
            if current is None:
                raise InputError(
                    "缩进续行没有所属消息",
                    stage="input",
                    hint=f"第 {line_no} 行先写消息头，或移除两个前导空格",
                )
            current["text"] = str(current["text"]) + "\n" + line[2:]
            current["line_end"] = line_no
            continue

        if line.strip() == "":
            flush()
            continue

        match = HEADER_RE.match(line)
        if not match:
            raise InputError(
                "无归属文本行",
                stage="input",
                hint=f"第 {line_no} 行需要以说话人标签加冒号开头，如 A: 文本",
            )

        label = match.group("label").strip()
        if label not in allowed:
            raise InputError(
                "出现未声明的说话人标签",
                stage="input",
                hint=f"第 {line_no} 行标签不在 --speaker-a/--speaker-b 中",
            )

        timestamp: datetime | None = None
        ts_raw = match.group("ts")
        if ts_raw is not None:
            timestamp = _parse_timestamp(ts_raw, line_no)

        rest = match.group("rest")
        if rest.startswith(" "):
            rest = rest[1:]

        flush()
        current = {
            "speaker": label,
            "text": rest,
            "timestamp": timestamp,
            "line_start": line_no,
            "line_end": line_no,
        }

    flush()

    if not messages:
        raise InputError("没有有效消息", stage="input", hint="检查消息头与正文格式")

    present = {m.speaker for m in messages}
    for label in (a, b):
        if label not in present:
            raise InputError(
                "至少一位说话人没有有效消息",
                stage="input",
                hint=f"确认文件中同时存在 {a} 与 {b} 的消息",
            )

    has_time = [m.timestamp is not None for m in messages]
    if any(has_time) and not all(has_time):
        warnings.append("部分消息带时间、部分不带时间；保持原始顺序，不做排序")
    timed = [m for m in messages if m.timestamp is not None]
    if timed:
        naive = sum(1 for m in timed if m.timestamp.tzinfo is None)  # type: ignore[union-attr]
        aware = len(timed) - naive
        if naive and aware:
            warnings.append("时间戳时区不一致，无法可靠比较；只使用原始顺序")
        for previous, nxt in zip(timed, timed[1:]):
            if not _comparable(previous.timestamp, nxt.timestamp):  # type: ignore[arg-type]
                continue
            if nxt.timestamp < previous.timestamp:  # type: ignore[operator]
                warnings.append("时间戳非单调；保持原始顺序，不排序")
                break

    session = 1
    for index, message in enumerate(messages):
        if index > 0:
            previous = messages[index - 1]
            boundary = False
            if (
                previous.timestamp is not None
                and message.timestamp is not None
                and _comparable(previous.timestamp, message.timestamp)
            ):
                boundary = message.timestamp - previous.timestamp > SESSION_GAP
            elif message.line_start > previous.line_end + 1:
                boundary = True
            if boundary:
                session += 1
        message.session_id = f"s{session:03d}"

    return ParsedChat(
        messages=messages,
        warnings=warnings,
        source_hash=source_hash,
        speaker_a=a,
        speaker_b=b,
    )
