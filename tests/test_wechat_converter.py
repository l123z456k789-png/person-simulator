from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from person_simulator.parser import parse_chat

SPEC = importlib.util.spec_from_file_location(
    "convert_wechat_md",
    Path(__file__).resolve().parents[1] / "tools" / "convert_wechat_md.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

SAMPLE = """# 测试聊天记录

- 消息数：4

## 2025-06-10

**[18:51:34] 翙**

第一行
第二行

**[18:52:00] 我**

收到。

**[18:53:00] 系统**

系统提示

**[18:54:00] 翙**

好。
"""


def test_convert_and_reparse(tmp_path):
    source = tmp_path / "export.md"
    source.write_text(SAMPLE, encoding="utf-8")
    output = tmp_path / "chat.txt"
    summary = MODULE.convert(
        source,
        output,
        speaker_a="翙",
        speaker_b="我",
    )
    assert summary["messages_total"] == 4
    assert summary["messages_included"] == 3
    assert summary["skipped_by_speaker"] == {"系统": 1}
    parsed = parse_chat(output, "翙", "我", target="翙")
    assert [message.speaker for message in parsed.messages] == ["翙", "我", "翙"]
    assert parsed.messages[0].text == "第一行\n第二行"
    assert parsed.messages[0].timestamp is not None
