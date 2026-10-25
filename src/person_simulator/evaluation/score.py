"""Offline scoring of human-collected evaluation data."""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from person_simulator.errors import EvidenceError, StorageError
from person_simulator.evaluation.prepare import DIMENSIONS
from person_simulator.storage import utcnow


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise StorageError("评估文件不可读", stage="eval", hint=str(path)) from exc
    rows = []
    for line in lines:
        if line.strip():
            try:
                value = json.loads(line)
            except ValueError as exc:
                raise EvidenceError("评估 JSONL 行损坏", stage="eval", hint=str(path)) from exc
            if not isinstance(value, dict):
                raise EvidenceError("评估 JSONL 行不是对象", stage="eval", hint=str(path))
            rows.append(value)
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise StorageError("评分 CSV 不可读", stage="eval", hint=str(path)) from exc


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def score_eval(
    *,
    bundle: str | Path,
    responses_path: str | Path,
    ratings_path: str | Path,
) -> dict[str, Any]:
    bundle_path = Path(bundle)
    cases = _read_jsonl(bundle_path / "cases.jsonl")
    case_by_id = {str(case["case_id"]): case for case in cases}
    if len(case_by_id) != len(cases):
        raise EvidenceError("cases.jsonl 存在重复 case_id", stage="eval")
    responses = _read_jsonl(Path(responses_path))
    ratings = _read_csv(Path(ratings_path))

    seen_responses: set[tuple[str, int]] = set()
    persona_hashes: set[str] = set()
    for response in responses:
        case_id = str(response.get("case_id", ""))
        if case_id not in case_by_id:
            raise EvidenceError("response 引用了未知 case_id", stage="eval", hint=case_id)
        try:
            repeat = int(response.get("repeat", 1))
        except (TypeError, ValueError) as exc:
            raise EvidenceError("response.repeat 不是整数", stage="eval", hint=case_id) from exc
        key = (case_id, repeat)
        if key in seen_responses:
            raise EvidenceError("response 重复（case_id + repeat）", stage="eval", hint=case_id)
        seen_responses.add(key)
        if str(response.get("source", "")) != "human_collected":
            raise EvidenceError(
                "拒绝用非人工采集的 response 生成真实评估",
                stage="eval",
                hint="Mock 回答只能用于测试评分器，不能证明人物效果",
            )
        value = str(response.get("persona_hash", "")).strip()
        if not value:
            raise EvidenceError("response 缺少 persona_hash", stage="eval", hint=case_id)
        persona_hashes.add(value)
    if len(persona_hashes) > 1:
        raise EvidenceError("responses 使用了多个 persona_hash", stage="eval")

    responses_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for response in responses:
        responses_by_case[str(response["case_id"])].append(response)
    repeats = {case_id: len(items) for case_id, items in responses_by_case.items()}
    min_repeats = min(repeats.values()) if repeats else 0

    seen_ratings: set[tuple[str, str, str]] = set()
    dimension_scores: dict[str, list[int]] = {dimension: [] for dimension in DIMENSIONS}
    distribution: dict[str, Counter[int]] = {dimension: Counter() for dimension in DIMENSIONS}
    identity_errors = 0
    fabricated_history = 0
    unsupported_ratings = 0
    missing_scores = 0
    per_case_rater: dict[str, dict[str, int]] = defaultdict(dict)

    for row in ratings:
        case_id = str(row.get("case_id", ""))
        if case_id not in case_by_id:
            raise EvidenceError("rating 引用了未知 case_id", stage="eval", hint=case_id)
        dimension = str(row.get("dimension", ""))
        if dimension not in DIMENSIONS:
            raise EvidenceError("rating.dimension 非法", stage="eval", hint=case_id)
        rater = str(row.get("rater", "")).strip()
        if not rater:
            raise EvidenceError("rating 缺少 rater", stage="eval", hint=case_id)
        key = (case_id, rater, dimension)
        if key in seen_ratings:
            raise EvidenceError("同一评审对同一题重复评分", stage="eval", hint=case_id)
        seen_ratings.add(key)

        if _truthy(row.get("unsupported_history")):
            unsupported_ratings += 1
            continue
        raw_score = str(row.get("score", "")).strip()
        if raw_score == "":
            missing_scores += 1
            continue
        try:
            score = int(raw_score)
        except ValueError as exc:
            raise EvidenceError("score 不是整数", stage="eval", hint=case_id) from exc
        if score < 1 or score > 5:
            raise EvidenceError("score 必须在 1—5", stage="eval", hint=case_id)
        dimension_scores[dimension].append(score)
        distribution[dimension][score] += 1
        per_case_rater[case_id][rater] = score
        if _truthy(row.get("identity_error")):
            identity_errors += 1
        if _truthy(row.get("fabricated_history")):
            fabricated_history += 1

    case_dimensions = Counter(str(case["primary_dimension"]) for case in cases)
    unsupported_cases = sum(1 for case in cases if case.get("status") == "unsupported")

    dimension_report: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        scores = dimension_scores[dimension]
        dimension_report[dimension] = {
            "mean": round(statistics.mean(scores), 3) if scores else None,
            "count": len(scores),
            "distribution": {
                str(score): distribution[dimension].get(score, 0) for score in range(1, 6)
            },
            "missing": sum(
                1
                for case in cases
                if case.get("primary_dimension") == dimension
                and case.get("status") != "unsupported"
            )
            - len(scores),
            "unsupported_cases": sum(
                1
                for case in cases
                if case.get("primary_dimension") == dimension
                and case.get("status") == "unsupported"
            ),
        }

    disagreements = []
    for case_id, by_rater in per_case_rater.items():
        if len(by_rater) >= 2 and max(by_rater.values()) - min(by_rater.values()) > 1:
            disagreements.append(
                {
                    "case_id": case_id,
                    "scores": by_rater,
                    "spread": max(by_rater.values()) - min(by_rater.values()),
                }
            )

    human_rated = sum(len(values) for values in dimension_scores.values())
    gate_counts = all(
        dimension_report[dimension]["count"] >= 6 for dimension in DIMENSIONS
    )
    gate_means = all(
        dimension_report[dimension]["mean"] is not None
        and dimension_report[dimension]["mean"] >= 4
        for dimension in DIMENSIONS
    )
    gate_passed = bool(
        gate_counts
        and gate_means
        and identity_errors == 0
        and fabricated_history == 0
        and min_repeats >= 2
    )
    if human_rated == 0:
        status = "insufficient_data"
    elif not gate_counts or min_repeats < 2:
        status = "insufficient_data"
    else:
        status = "evaluated"

    report = {
        "status": status,
        "synthetic": False,
        "gate_passed": gate_passed,
        "gate": {
            "all_dimensions_mean_ge_4": gate_means,
            "each_dimension_count_ge_6": gate_counts,
            "no_identity_error": identity_errors == 0,
            "no_fabricated_history": fabricated_history == 0,
            "min_repeats_ge_2": min_repeats >= 2,
        },
        "persona_hash": next(iter(persona_hashes), None),
        "cases_total": len(cases),
        "cases_unsupported": unsupported_cases,
        "case_slots_by_dimension": dict(case_dimensions),
        "responses_total": len(responses),
        "responses_min_repeats": min_repeats,
        "ratings_total": len(ratings),
        "scores_total": human_rated,
        "missing_scores": missing_scores,
        "unsupported_history_ratings": unsupported_ratings,
        "identity_errors": identity_errors,
        "fabricated_history": fabricated_history,
        "disagreements": disagreements,
        "dimensions": dimension_report,
        "limitations": [
            "评分反映评审者对可见证据的主观判断，不是人格复制概率。",
            "新情境题没有唯一标准答案。",
            "只有真实采集、人工确认的数据才可视为 evaluated。",
        ],
        "created_at": utcnow().isoformat(),
    }
    return report


def write_quality_report(report: dict[str, Any], bundle: str | Path) -> tuple[Path, Path]:
    bundle_path = Path(bundle)
    json_path = bundle_path / "quality_report.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# quality_report",
        "",
        f"- status: {report['status']}",
        f"- gate_passed: {report['gate_passed']}",
        f"- persona_hash: {report.get('persona_hash')}",
        f"- cases: {report['cases_total']}（unsupported {report['cases_unsupported']}）",
        f"- responses: {report['responses_total']}，最少重复次数: {report['responses_min_repeats']}",
        f"- ratings: {report['ratings_total']}，有效评分: {report['scores_total']}",
        f"- identity_errors: {report['identity_errors']}",
        f"- fabricated_history: {report['fabricated_history']}",
        "",
        "| 维度 | 均值 | 有效数 | 缺失 | unsupported |",
        "|---|---:|---:|---:|---:|",
    ]
    for dimension, values in report["dimensions"].items():
        lines.append(
            f"| {dimension} | {values['mean'] if values['mean'] is not None else '—'} | "
            f"{values['count']} | {values['missing']} | {values['unsupported_cases']} |"
        )
    lines.extend(
        [
            "",
            "## 局限",
            "",
            *[f"- {item}" for item in report["limitations"]],
            "",
        ]
    )
    md_path = bundle_path / "quality_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
