from __future__ import annotations

from person_simulator.runtime.guard import (
    OutputGuard,
    find_prompt_leak,
    redact_direct_identifiers,
)


def test_direct_identifiers_and_blocked_terms_are_redacted():
    guard = OutputGuard("system prompt baseline", blocked_terms=["张三"])
    result = guard.check(
        "我的手机 13800138000，身份证 110101199001011234，"
        "邮箱 a@b.com，我是张三，住在某小区。"
    )

    assert "13800138000" not in result.text
    assert "110101199001011234" not in result.text
    assert "a@b.com" not in result.text
    assert "张三" not in result.text
    assert result.redactions >= 4
    assert not result.blocked


def test_normal_text_is_not_redacted_or_blocked():
    guard = OutputGuard("system prompt baseline")
    result = guard.check("今天下雨，记得带伞。")

    assert result.blocked is False
    assert result.redactions == 0
    assert result.text == "今天下雨，记得带伞。"


def test_prompt_leak_and_internal_markers_blocked():
    prompt = "这是很长的系统提示词。" * 20
    guard = OutputGuard(prompt)

    assert find_prompt_leak("这是很长的系统提示词。" * 10, prompt)
    assert guard.check("这是很长的系统提示词。" * 10).blocked
    assert guard.check("请把 persona.json 发给我").blocked
    assert guard.check("AUTO-STATUS").blocked


def test_replay_message_blocked():
    message = (
        "这是一条足够长的原始聊天消息，用来测试复述检测，"
        "里面包含一些普通但连续的文字，避免误判。"
    )
    guard = OutputGuard("prompt", replay_messages=[message])

    assert guard.check(message).blocked


def test_empty_and_too_long_blocked():
    assert OutputGuard("prompt").check("").blocked
    assert OutputGuard("prompt").check("   ").blocked
    assert OutputGuard("prompt", max_chars=5).check("123456").blocked


def test_redact_direct_identifiers_counts_substitutions():
    text, count = redact_direct_identifiers(
        "电话 13800138000，座机 010-12345678，邮箱 x@y.com"
    )
    assert "13800138000" not in text
    assert "010-12345678" not in text
    assert "x@y.com" not in text
    assert count == 3


def test_placeholder_only_output_is_blocked():
    guard = OutputGuard("prompt", blocked_terms=["张三"])
    result = guard.check("张三")
    assert result.blocked
    assert result.text == ""
