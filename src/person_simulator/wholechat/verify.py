"""Objective checks for whole-chat outputs."""

from __future__ import annotations

import re

from person_simulator.errors import EvidenceError, PipelineError
from person_simulator.models import Message

TAG_RE = r"<{tag}>(.*?)</{tag}>"
REF_RE = re.compile(r"(?<![\w])m(\d{1,6})(?![\w])")


def extract_tag(text: str, tag: str) -> str | None:
    match = re.search(TAG_RE.format(tag=re.escape(tag)), text, re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


def verify_message_refs(text: str, messages: dict[str, Message]) -> list[str]:
    refs = {f"m{int(number):06d}" for number in REF_RE.findall(text)}
    missing = sorted(ref for ref in refs if ref not in messages)
    if missing:
        raise EvidenceError(
            "输出引用了不存在的消息 ID",
            stage="wholechat",
            hint="、".join(missing[:10]),
        )
    return sorted(refs)


def verify_whole_output(
    *,
    response_text: str,
    system_prompt: str,
    profile: str | None,
    messages: dict[str, Message],
    is_mock: bool,
) -> list[str]:
    if not system_prompt.strip():
        raise PipelineError("模型没有返回系统提示词", stage="wholechat")
    if len(system_prompt) > 30000:
        raise PipelineError(
            "系统提示词过长，拒绝发布",
            stage="wholechat",
            hint="要求更精简的系统提示词",
        )
    refs = verify_message_refs(system_prompt, messages)
    if profile:
        refs = sorted(set(refs) | set(verify_message_refs(profile, messages)))
    if is_mock and "MOCK" not in (system_prompt + (profile or "")).upper():
        raise PipelineError("Mock 产物缺少 MOCK 标识", stage="wholechat")
    lowered = (system_prompt + (profile or "")).lower()
    for marker in ("```include", "!http://", "!https://"):
        if marker in lowered:
            raise PipelineError("输出包含外部依赖", stage="wholechat")
    return refs
