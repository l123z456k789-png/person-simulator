"""Build a leakage-safe human evaluation bundle."""

from __future__ import annotations

import csv
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from person_simulator.errors import PipelineError, StorageError
from person_simulator.models import Message
from person_simulator.parser import ParsedChat, parse_chat
from person_simulator.storage import utcnow

DIMENSIONS = ["language", "behavior", "attitude", "novel_situation", "history_accuracy"]
SLOTS_PER_DIMENSION = 6
HOLDOUT_RATIO = 0.2
MIN_SESSIONS = 5

NOVEL_PROMPTS = [
    "假设你临时被安排到陌生城市工作一周，你会怎么跟对方说？",
    "假设对方突然取消你们约好的计划，你会怎么回应？",
    "假设有人请你帮忙但你很累，你会怎么拒绝？",
    "假设你在群里被误解，你会怎么解释？",
    "假设对方送你一件你不喜欢的礼物，你会说什么？",
    "假设你需要向对方道歉，你会怎么开口？",
]

UNKNOWN_HISTORY_PROMPTS = [
    ("你小时候最好的朋友叫什么名字？", "材料未提供，应承认不知道，不应编造姓名。"),
    ("你第一次学会骑自行车是几岁？", "材料未提供，应承认不知道，不应编造年龄。"),
    ("你最喜欢的一次旅行发生在哪一年？", "材料未提供，应承认不知道，不应编造年份。"),
]


@dataclass
class PrepareResult:
    bundle: Path
    status: str
    cases: int
    reason: str | None = None


def serialize_messages(messages: list[Message]) -> str:
    blocks: list[str] = []
    for message in messages:
        prefix = f"[{message.timestamp.isoformat()}] " if message.timestamp else ""
        lines = message.text.split("\n")
        first = lines[0]
        block = [f"{prefix}{message.speaker}: {first}"]
        block.extend(f"  {line}" for line in lines[1:])
        blocks.append("\n".join(block))
    return "\n\n".join(blocks) + "\n"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _session_groups(parsed: ParsedChat) -> list[list[Message]]:
    groups: dict[str, list[Message]] = {}
    order: list[str] = []
    for message in parsed.messages:
        if message.session_id not in groups:
            groups[message.session_id] = []
            order.append(message.session_id)
        groups[message.session_id].append(message)
    return [groups[session_id] for session_id in order]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _context_for(
    session_messages: list[Message], position: int, limit: int = 3
) -> list[dict[str, Any]]:
    start = max(0, position - limit)
    return [
        {
            "message_id": message.id,
            "speaker": message.speaker,
            "text": message.text,
            "timestamp": message.timestamp.isoformat() if message.timestamp else None,
        }
        for message in session_messages[start:position]
    ]


def _prompt_for(dimension: str, target: str, interlocutor: str, context: list[dict[str, Any]]) -> str:
    last = context[-1]["text"] if context else ""
    if dimension == "language":
        return (
            f"请只以{target}的口吻回复下面这句话，保持你平时的说话风格：{last}"
        )
    if dimension == "behavior":
        joined = " / ".join(item["text"] for item in context[-2:])
        return (
            f"情境：{target}与{interlocutor}的对话进行到“{joined}”。"
            f"请以{target}的方式回应。"
        )
    return (
        f"你（{target}）正在和{interlocutor}聊天。对方最后说：{last}。请直接回应对方。"
    )


def _guide(target: str, interlocutor: str) -> str:
    return f"""# 人物模拟评估指南

本包评估的是 `person_simulation.md` 在网页版 AI 中扮演 **{target}**（对话对象为 **{interlocutor}**）的表现，不是人格复制概率。

## 使用步骤

1. 用 `train_chat.txt` 重新执行 `build`（不要用全量聊天建模，否则留出集泄漏）。
2. 记录生成文件的 SHA256，填入每条 response 的 `persona_hash`。
3. 把 `person_simulation.md` 上传到选定网页版 AI，开启新会话。
4. 按 `cases.jsonl` 逐题提问；`reviewer_references.json` 只给评审者，不要给被测模型。
5. 把回答填入 `responses.jsonl`，至少同一条件下重复两次。
6. 至少一位了解原人物的评审按 `ratings.template.csv` 打分；推荐两人独立盲评。
7. 运行 `python -m person_simulator eval score --bundle <本目录> --responses responses.jsonl --ratings ratings.csv`。

## 评分锚点

- 1 = 明显不符合或违背证据
- 3 = 部分符合但明显泛化
- 4 = 符合可见习惯，仅有轻微偏差
- 5 = 符合可见习惯且无明显冲突

`unsupported_history` 标记资料本身不足的历史题；`identity_error` 标记认错人/角色混淆；`fabricated_history` 标记编造未给出历史。评分不是“像本人”的概率。

## 五维与八项覆盖的对应

- `language`：语言风格相似性 + 表达长度/语气一致性
- `behavior`：行为模式一致性 + 情绪反应合理性（含冲突应对）
- `attitude`：对另一位参与者的态度一致性
- `novel_situation`：新情境下的模拟表现 + 未出现事件的合理推演
- `history_accuracy`：聊天中已出现事实的准确性 + 未出现事实的承认未知

不要把同一题重复计入两个维度；需要更细的结论时，在备注里写明失败类型。

## 状态

- `not_evaluated`：没有真实采集与人工评分。
- `insufficient_data`：样本、重复次数或维度覆盖不足。
- `evaluated`：真实采集、人工确认且达到最低样本门槛；仍需看具体分数与局限。

Mock 回答或合成评分只能测试评分器计算，不能证明真实效果。
"""


def prepare_eval(
    input_path: str | Path,
    *,
    target: str,
    speaker_a: str = "A",
    speaker_b: str = "B",
    out: str | Path,
) -> PrepareResult:
    parsed = parse_chat(input_path, speaker_a, speaker_b, target=target)
    interlocutor = parsed.speaker_b if target == parsed.speaker_a else parsed.speaker_a
    bundle = Path(out)
    if bundle.exists() and any(bundle.iterdir()):
        raise StorageError("评估输出目录非空，拒绝覆盖", stage="eval", hint=str(bundle))
    bundle.mkdir(parents=True, exist_ok=True)

    sessions = _session_groups(parsed)
    (bundle / "evaluation_guide.md").write_text(
        _guide(target, interlocutor), encoding="utf-8"
    )

    if len(sessions) < MIN_SESSIONS:
        manifest = {
            "status": "insufficient_data",
            "reason": f"可分会话只有 {len(sessions)} 个，少于 {MIN_SESSIONS} 个；不随机打散单条消息。",
            "source_hash": parsed.source_hash,
            "target": target,
            "interlocutor": interlocutor,
            "train_session_ids": [],
            "holdout_session_ids": [],
            "created_at": utcnow().isoformat(),
        }
        _write_json(bundle / "split_manifest.json", manifest)
        return PrepareResult(bundle=bundle, status="insufficient_data", cases=0, reason=manifest["reason"])

    holdout_count = max(1, int(round(len(sessions) * HOLDOUT_RATIO)))
    holdout_count = min(holdout_count, len(sessions) - 1)
    train_sessions = sessions[:-holdout_count]
    holdout_sessions = sessions[-holdout_count:]
    train_messages = [message for session in train_sessions for message in session]
    holdout_messages = [message for session in holdout_sessions for message in session]

    train_text = serialize_messages(train_messages)
    train_path = bundle / "train_chat.txt"
    train_path.write_text(train_text, encoding="utf-8")
    check = parse_chat(train_path, speaker_a, speaker_b, target=target)
    if [m.text for m in check.messages] != [m.text for m in train_messages]:
        raise PipelineError("train_chat.txt 回读后与训练消息不一致", stage="eval")

    _write_jsonl(
        bundle / "holdout.jsonl",
        [message.model_dump(mode="json") for message in holdout_messages],
    )

    cases: list[dict[str, Any]] = []
    references: dict[str, Any] = {}
    used_target_ids: set[str] = set()

    def add_case(dimension: str, case: dict[str, Any], reference: dict[str, Any]) -> None:
        case_id = f"case-{len(cases) + 1:04d}"
        case["case_id"] = case_id
        case["slot"] = len(cases) + 1
        case["primary_dimension"] = dimension
        case["needs_review"] = True
        cases.append(case)
        references[case_id] = reference

    for dimension in ("language", "behavior", "attitude"):
        produced = 0
        for session in holdout_sessions:
            for position, message in enumerate(session):
                if produced >= SLOTS_PER_DIMENSION:
                    break
                if message.speaker != target or position == 0 or message.id in used_target_ids:
                    continue
                context = _context_for(session, position)
                if not context:
                    continue
                used_target_ids.add(message.id)
                add_case(
                    dimension,
                    {
                        "status": "candidate",
                        "prompt": _prompt_for(dimension, target, interlocutor, context),
                        "context_messages": context,
                        "source_message_ids": [item["message_id"] for item in context] + [message.id],
                        "reference_message_ids": [message.id],
                    },
                    {
                        "reference_answer": message.text,
                        "reference_message_ids": [message.id],
                        "visible_in_training": False,
                        "notes": "留出会话中的目标真实回复，仅评审者可见。",
                    },
                )
                produced += 1
            if produced >= SLOTS_PER_DIMENSION:
                break
        while produced < SLOTS_PER_DIMENSION:
            add_case(
                dimension,
                {
                    "status": "unsupported",
                    "reason": "留出集中缺少足够的带上下文目标回复。",
                    "prompt": "",
                    "context_messages": [],
                    "source_message_ids": [],
                    "reference_message_ids": [],
                },
                {"reference_answer": None, "notes": "unsupported，不计入评分。"},
            )
            produced += 1

    for index, prompt in enumerate(NOVEL_PROMPTS):
        add_case(
            "novel_situation",
            {
                "status": "candidate",
                "prompt": prompt,
                "context_messages": [],
                "source_message_ids": [],
                "reference_message_ids": [],
            },
            {
                "reference_answer": None,
                "notes": "新情境没有唯一标准答案；按已有偏好与反应模式评审。",
                "hypothetical": True,
            },
        )

    history_candidates = [
        message
        for message in train_messages
        if message.speaker == target and len(message.text) >= 8
    ]
    preferred = [
        message
        for message in history_candidates
        if any(word in message.text for word in ("昨天", "上次", "之前", "那天", "以前", "去年"))
    ]
    pool = preferred + [message for message in history_candidates if message not in preferred]
    for index in range(3):
        if index < len(pool):
            message = pool[index]
            snippet = message.text[:60]
            add_case(
                "history_accuracy",
                {
                    "status": "candidate",
                    "prompt": f"你之前说过“{snippet}”。能按你当时的说法再说一遍吗？",
                    "context_messages": [],
                    "source_message_ids": [message.id],
                    "reference_message_ids": [message.id],
                },
                {
                    "reference_answer": message.text,
                    "reference_message_ids": [message.id],
                    "visible_in_training": True,
                    "notes": "仅使用训练可见历史；核对是否逐字或语义一致，不要求逐字复制整段。",
                },
            )
        else:
            add_case(
                "history_accuracy",
                {
                    "status": "unsupported",
                    "reason": "训练集缺少足够的有据历史。",
                    "prompt": "",
                    "context_messages": [],
                    "source_message_ids": [],
                    "reference_message_ids": [],
                },
                {"reference_answer": None, "notes": "unsupported，不计入评分。"},
            )
    for prompt, expectation in UNKNOWN_HISTORY_PROMPTS:
        add_case(
            "history_accuracy",
            {
                "status": "candidate",
                "prompt": prompt,
                "context_messages": [],
                "source_message_ids": [],
                "reference_message_ids": [],
            },
            {
                "reference_answer": expectation,
                "notes": "材料从未提供；正确行为是承认不知道，而不是编造。",
                "expected_unknown": True,
                "visible_in_training": False,
            },
        )

    _write_jsonl(bundle / "cases.jsonl", cases)
    _write_json(bundle / "reviewer_references.json", references)
    _write_jsonl(
        bundle / "responses.template.jsonl",
        [
            {
                "case_id": case["case_id"],
                "repeat": repeat,
                "platform": "",
                "model_visible_name": "",
                "date": "",
                "persona_hash": "",
                "response": "",
                "source": "human_collected",
            }
            for case in cases
            for repeat in (1, 2)
        ],
    )
    with (bundle / "ratings.template.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case_id",
                "run_id",
                "rater",
                "dimension",
                "score",
                "unsupported_history",
                "identity_error",
                "fabricated_history",
                "notes",
            ]
        )

    split_manifest = {
        "status": "prepared",
        "source_hash": parsed.source_hash,
        "target": target,
        "interlocutor": interlocutor,
        "train_source_hash": _hash_text(train_text),
        "holdout_source_hash": _hash_text(
            "\n".join(json.dumps(message.model_dump(mode="json"), ensure_ascii=False) for message in holdout_messages)
        ),
        "train_session_ids": [session[0].session_id for session in train_sessions],
        "holdout_session_ids": [session[0].session_id for session in holdout_sessions],
        "train_message_range": [train_messages[0].id, train_messages[-1].id],
        "holdout_message_range": [holdout_messages[0].id, holdout_messages[-1].id],
        "holdout_ratio": HOLDOUT_RATIO,
        "min_sessions": MIN_SESSIONS,
        "created_at": utcnow().isoformat(),
        "notes": "按完整会话划分；未随机打散单条消息；评测时必须用 train_chat.txt 重新建模。",
    }
    _write_json(bundle / "split_manifest.json", split_manifest)
    return PrepareResult(bundle=bundle, status="prepared", cases=len(cases))
