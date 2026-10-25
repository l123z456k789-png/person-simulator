from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from person_simulator.errors import EvidenceError
from person_simulator.evaluation.prepare import prepare_eval
from person_simulator.evaluation.score import score_eval, write_quality_report


def _long_chat(tmp_path: Path) -> Path:
    lines = []
    for session in range(8):
        for index in range(20):
            speaker = "A" if index % 2 == 0 else "B"
            lines.append(f"{speaker}: 会话{session}第{index}条消息内容。")
        lines.append("")
    path = tmp_path / "chat.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_prepare_creates_30_slot_bundle_without_leakage(tmp_path):
    result = prepare_eval(_long_chat(tmp_path), target="A", out=tmp_path / "bundle")
    assert result.status == "prepared"
    assert result.cases == 30
    bundle = result.bundle
    for name in (
        "train_chat.txt",
        "holdout.jsonl",
        "cases.jsonl",
        "reviewer_references.json",
        "responses.template.jsonl",
        "ratings.template.csv",
        "evaluation_guide.md",
        "split_manifest.json",
    ):
        assert (bundle / name).is_file(), name

    split = json.loads((bundle / "split_manifest.json").read_text(encoding="utf-8"))
    assert split["status"] == "prepared"
    assert set(split["train_session_ids"]).isdisjoint(split["holdout_session_ids"])
    cases = [json.loads(line) for line in (bundle / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(cases) == 30
    from collections import Counter

    assert Counter(case["primary_dimension"] for case in cases)["language"] == 6
    assert Counter(case["primary_dimension"] for case in cases)["history_accuracy"] == 6
    assert all("reference_answer" not in case for case in cases)


def test_insufficient_sessions(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text("A: 一\nB: 二\n\nA: 三\nB: 四\n", encoding="utf-8")
    result = prepare_eval(path, target="A", out=tmp_path / "bundle")
    assert result.status == "insufficient_data"
    assert result.cases == 0
    assert (tmp_path / "bundle" / "split_manifest.json").is_file()


def _fill_bundle(bundle: Path, *, mock: bool = False) -> tuple[Path, Path]:
    cases = [json.loads(line) for line in (bundle / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    responses = []
    for case in cases:
        for repeat in (1, 2):
            responses.append(
                {
                    "case_id": case["case_id"],
                    "repeat": repeat,
                    "platform": "test",
                    "model_visible_name": "unknown",
                    "date": "2026-10-23",
                    "persona_hash": "abc123",
                    "response": "回答",
                    "source": "mock" if mock else "human_collected",
                }
            )
    responses_path = bundle / "responses.jsonl"
    responses_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in responses) + "\n",
        encoding="utf-8",
    )
    ratings_path = bundle / "ratings.csv"
    with ratings_path.open("w", encoding="utf-8", newline="") as handle:
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
        for case in cases:
            writer.writerow(
                [
                    case["case_id"],
                    "run1",
                    "rater1",
                    case["primary_dimension"],
                    5,
                    "false",
                    "false",
                    "false",
                    "",
                ]
            )
    return responses_path, ratings_path


def test_score_rejects_mock_responses(tmp_path):
    result = prepare_eval(_long_chat(tmp_path), target="A", out=tmp_path / "bundle")
    responses, ratings = _fill_bundle(result.bundle, mock=True)
    with pytest.raises(EvidenceError):
        score_eval(bundle=result.bundle, responses_path=responses, ratings_path=ratings)


def test_score_evaluates_human_data_and_writes_report(tmp_path):
    result = prepare_eval(_long_chat(tmp_path), target="A", out=tmp_path / "bundle")
    responses, ratings = _fill_bundle(result.bundle)
    report = score_eval(bundle=result.bundle, responses_path=responses, ratings_path=ratings)
    assert report["status"] == "evaluated"
    assert report["gate_passed"] is True
    assert report["identity_errors"] == 0
    assert report["fabricated_history"] == 0
    json_path, md_path = write_quality_report(report, result.bundle)
    assert json_path.is_file() and md_path.is_file()
