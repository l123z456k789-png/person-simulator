from __future__ import annotations

from person_simulator.models import ExampleCandidate, Message
from person_simulator.modeling.persona import build_examples
from person_simulator.textstats import language_stats


def _message(index: int, speaker: str, text: str) -> Message:
    return Message(
        id=f"m{index:06d}",
        index=index - 1,
        speaker=speaker,
        text=text,
        timestamp=None,
        line_start=index,
        line_end=index,
        session_id="s001",
    )


def test_language_stats_counts_target_only():
    messages = [
        _message(1, "A", "你好"),
        _message(2, "B", "在吗？"),
        _message(3, "A", "在吗？🙂"),
        _message(4, "B", "嗯"),
        _message(5, "A", "第一行\n第二行"),
        _message(6, "A", "谢谢谢谢"),
    ]
    stats = language_stats(messages, "A")
    assert stats.total_messages == 4
    assert stats.shortest_chars == 2
    assert stats.longest_chars == 7
    assert stats.multiline_messages == 1
    assert stats.question_messages == 1
    assert stats.emoji_messages == 1
    assert stats.punctuation_chars == 1
    assert stats.bigram_total > 0
    assert any(pair == "谢谢" and count >= 2 for pair, count in stats.top_bigrams)


def test_examples_cover_multiple_situations():
    messages = [
        _message(1, "A", "今天吃什么？"),
        _message(2, "B", "随便。"),
        _message(3, "A", "不行，说一个。"),
        _message(4, "B", "那就面吧。"),
        _message(5, "A", "对不起，我昨天语气不好。"),
        _message(6, "B", "没事。"),
        _message(7, "A", "谢谢你陪我。"),
        _message(8, "B", "嗯。"),
        _message(9, "A", "早安。"),
        _message(10, "B", "早。"),
    ]
    by_id = {message.id: message for message in messages}
    candidates = [
        ExampleCandidate(message_ids=["m000001", "m000002"]),
        ExampleCandidate(message_ids=["m000003", "m000004"]),
        ExampleCandidate(message_ids=["m000005", "m000006"]),
        ExampleCandidate(message_ids=["m000007", "m000008"]),
        ExampleCandidate(message_ids=["m000009", "m000010"]),
    ]
    examples, _ = build_examples(
        candidates,
        messages=by_id,
        message_order=[message.id for message in messages],
        target="A",
    )
    assert len(examples) == 5
    joined = " ".join(example.situation for example in examples)
    for category in ("日常交流", "拒绝/边界", "修复/道歉", "亲近/感谢"):
        assert category in joined
    assert [example.id for example in examples] == [f"ex{number:03d}" for number in range(1, 6)]
