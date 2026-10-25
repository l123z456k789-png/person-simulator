"""Code-derived surface statistics for the target speaker.

These are descriptive counts, not psychological inference. Every rate
reports its denominator.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from person_simulator.models import Message

EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")
PUNCTUATION = set("，。！？、；：,.!?;:\"'“”‘’（）()【】[]…—～~")
QUESTION_MARKS = ("?", "？")
EXCLAMATION_MARKS = ("!", "！")


@dataclass(frozen=True)
class LanguageStats:
    total_messages: int
    total_chars: int
    average_chars: float
    median_chars: float
    shortest_chars: int
    longest_chars: int
    multiline_messages: int
    question_messages: int
    exclamation_messages: int
    emoji_messages: int
    punctuation_chars: int
    punctuation_rate: float
    top_bigrams: list[tuple[str, int]] = field(default_factory=list)
    bigram_total: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "total_messages": self.total_messages,
            "total_chars": self.total_chars,
            "average_chars": self.average_chars,
            "median_chars": self.median_chars,
            "shortest_chars": self.shortest_chars,
            "longest_chars": self.longest_chars,
            "multiline_messages": self.multiline_messages,
            "question_messages": self.question_messages,
            "exclamation_messages": self.exclamation_messages,
            "emoji_messages": self.emoji_messages,
            "punctuation_chars": self.punctuation_chars,
            "punctuation_rate": self.punctuation_rate,
            "top_bigrams": self.top_bigrams,
            "bigram_total": self.bigram_total,
        }


def _count_bigrams(texts: Iterable[str]) -> tuple[list[tuple[str, int]], int]:
    counter: Counter[str] = Counter()
    for text in texts:
        chars = [
            char
            for char in text
            if not char.isspace() and char not in PUNCTUATION and not EMOJI_RE.match(char)
        ]
        for index in range(len(chars) - 1):
            counter[chars[index] + chars[index + 1]] += 1
    total = sum(counter.values())
    top = [(pair, count) for pair, count in counter.most_common(5) if count >= 2]
    return top, total


def language_stats(messages: Iterable[Message], target: str) -> LanguageStats:
    target_messages = [message for message in messages if message.speaker == target]
    texts = [message.text for message in target_messages]
    lengths = [len(text) for text in texts]
    total_chars = sum(lengths)
    punctuation_chars = sum(
        1 for text in texts for char in text if char in PUNCTUATION
    )
    top_bigrams, bigram_total = _count_bigrams(texts)
    count = len(texts)
    return LanguageStats(
        total_messages=count,
        total_chars=total_chars,
        average_chars=round(total_chars / count, 1) if count else 0.0,
        median_chars=float(statistics.median(lengths)) if lengths else 0.0,
        shortest_chars=min(lengths) if lengths else 0,
        longest_chars=max(lengths) if lengths else 0,
        multiline_messages=sum(1 for text in texts if "\n" in text),
        question_messages=sum(
            1 for text in texts if any(mark in text for mark in QUESTION_MARKS)
        ),
        exclamation_messages=sum(
            1 for text in texts if any(mark in text for mark in EXCLAMATION_MARKS)
        ),
        emoji_messages=sum(1 for text in texts if EMOJI_RE.search(text)),
        punctuation_chars=punctuation_chars,
        punctuation_rate=round(punctuation_chars / total_chars, 3) if total_chars else 0.0,
        top_bigrams=top_bigrams,
        bigram_total=bigram_total,
    )


def stats_lines(stats: LanguageStats) -> list[str]:
    if stats.total_messages == 0:
        return ["材料不足，没有目标消息可统计。"]
    return [
        f"- 目标消息 {stats.total_messages} 条；平均每条 {stats.average_chars} 字符（中位 {stats.median_chars:g}，最短 {stats.shortest_chars}，最长 {stats.longest_chars}）",
        f"- 多行消息 {stats.multiline_messages} 条；含问号 {stats.question_messages} 条；含感叹号 {stats.exclamation_messages} 条；含 emoji {stats.emoji_messages} 条",
        f"- 标点字符 {stats.punctuation_chars} 个，占目标正文 {stats.punctuation_rate:.1%}（分母：{stats.total_chars} 字符）",
    ]


def bigram_line(stats: LanguageStats) -> str | None:
    if not stats.top_bigrams:
        return None
    joined = "、".join(f"“{pair}”×{count}" for pair, count in stats.top_bigrams)
    return f"高频字符二元组（仅表面统计）：{joined}；分母 {stats.bigram_total} 个二元组。"
