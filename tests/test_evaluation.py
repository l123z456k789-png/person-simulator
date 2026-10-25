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


RATING_HEADER = [
    "case_id",
    "run_id",
    "rater",
    "dimension",
    "score",
    "unsupported_history",
    "identity_error",
    "fabricated_history",
    "factual_error",
    "unsupported_inference",
    "notes",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RATING_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


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
    _write_jsonl(responses_path, responses)
    ratings_path = bundle / "ratings.csv"
    _write_csv(
        ratings_path,
        [
            {
                "case_id": case["case_id"],
                "run_id": "run1",
                "rater": "rater1",
                "dimension": case["primary_dimension"],
                "score": "5",
                "unsupported_history": "false",
                "identity_error": "false",
                "fabricated_history": "false",
                "factual_error": "false",
                "unsupported_inference": "false",
                "notes": "",
            }
            for case in cases
        ],
    )
    return responses_path, ratings_path


def test_responses_template_excludes_unsupported_cases(tmp_path):
    path = tmp_path / "short-holdout.txt"
    lines = []
    for session in range(6):
        for index in range(20):
            speaker = "A" if index % 2 == 0 else "B"
            lines.append(f"{speaker}: 会话{session}第{index}条消息内容。")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")

    result = prepare_eval(path, target="A", out=tmp_path / "bundle")
    cases = _read_jsonl(result.bundle / "cases.jsonl")
    supported = {case["case_id"] for case in cases if case["status"] == "candidate"}
    unsupported = {case["case_id"] for case in cases if case["status"] == "unsupported"}
    template = _read_jsonl(result.bundle / "responses.template.jsonl")

    assert unsupported
    assert {row["case_id"] for row in template} == supported
    assert not ({row["case_id"] for row in template} & unsupported)


def test_ratings_template_contains_supported_cases(tmp_path):
    result = prepare_eval(_long_chat(tmp_path), target="A", out=tmp_path / "bundle")
    cases = _read_jsonl(result.bundle / "cases.jsonl")
    supported = {case["case_id"] for case in cases if case["status"] == "candidate"}
    rows = _read_csv(result.bundle / "ratings.template.csv")

    assert len(rows) == len(supported)
    assert {row["case_id"] for row in rows} == supported
    assert all(row["score"] == "" for row in rows)
    assert all(row["dimension"] for row in rows)


def test_prepare_prompts_include_the_full_context(tmp_path):
    result = prepare_eval(_long_chat(tmp_path), target="A", out=tmp_path / "bundle")
    cases = _read_jsonl(result.bundle / "cases.jsonl")
    case = next(
        item
        for item in cases
        if item["primary_dimension"] == "language"
        and item["status"] == "candidate"
    )

    assert len(case["context_messages"]) >= 2
    for item in case["context_messages"]:
        assert item["text"] in case["prompt"]


def test_prepare_manifest_records_context_case_format(tmp_path):
    result = prepare_eval(_long_chat(tmp_path), target="A", out=tmp_path / "bundle")
    split = json.loads(
        (result.bundle / "split_manifest.json").read_text(encoding="utf-8")
    )

    assert split["case_format"] == "context-v2"


def test_score_requires_repeats_for_every_supported_case(tmp_path):
    result = prepare_eval(_long_chat(tmp_path), target="A", out=tmp_path / "bundle")
    responses, ratings = _fill_bundle(result.bundle)
    cases = _read_jsonl(result.bundle / "cases.jsonl")
    missing_case = cases[0]["case_id"]
    remaining = [row for row in _read_jsonl(responses) if row["case_id"] != missing_case]
    _write_jsonl(responses, remaining)

    report = score_eval(bundle=result.bundle, responses_path=responses, ratings_path=ratings)

    assert report["responses_min_repeats"] == 0
    assert report["status"] == "insufficient_data"
    assert report["gate"]["all_supported_cases_have_repeats"] is False


def test_score_requires_every_supported_case_to_be_rated(tmp_path):
    result = prepare_eval(_long_chat(tmp_path), target="A", out=tmp_path / "bundle")
    responses, ratings = _fill_bundle(result.bundle)
    cases = _read_jsonl(result.bundle / "cases.jsonl")
    missing_case = next(
        case["case_id"] for case in cases if case["primary_dimension"] == "language"
    )
    first_rater = [
        row for row in _read_csv(ratings) if row["case_id"] != missing_case
    ]
    second_rater = [
        {**row, "rater": "rater2"}
        for row in first_rater
    ]
    _write_csv(ratings, [*first_rater, *second_rater])

    report = score_eval(bundle=result.bundle, responses_path=responses, ratings_path=ratings)

    assert report["status"] == "insufficient_data"
    assert report["gate"]["all_supported_cases_rated"] is False
    assert report["unrated_supported_cases"] == [missing_case]
    assert report["dimensions"]["language"]["count"] == 10
    assert report["dimensions"]["language"]["missing"] == 1


def test_score_counts_factual_errors_and_unsupported_inference(tmp_path):
    result = prepare_eval(_long_chat(tmp_path), target="A", out=tmp_path / "bundle")
    responses, ratings = _fill_bundle(result.bundle)
    rows = _read_csv(ratings)
    rows[0]["factual_error"] = "true"
    rows[1]["unsupported_inference"] = "true"
    _write_csv(ratings, rows)

    report = score_eval(bundle=result.bundle, responses_path=responses, ratings_path=ratings)

    assert report["factual_errors"] == 1
    assert report["unsupported_inferences"] == 1
    assert report["gate"]["no_factual_error"] is False
    assert report["gate"]["no_unsupported_inference"] is False
    assert report["gate_passed"] is False


def test_score_rejects_dimension_mismatch(tmp_path):
    result = prepare_eval(_long_chat(tmp_path), target="A", out=tmp_path / "bundle")
    responses, ratings = _fill_bundle(result.bundle)
    rows = _read_csv(ratings)
    rows[0]["dimension"] = "behavior" if rows[0]["dimension"] == "language" else "language"
    _write_csv(ratings, rows)

    with pytest.raises(EvidenceError):
        score_eval(bundle=result.bundle, responses_path=responses, ratings_path=ratings)


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
