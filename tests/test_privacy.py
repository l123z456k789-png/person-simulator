from __future__ import annotations

import pytest

from person_simulator.errors import PrivacyError
from person_simulator.privacy import apply_privacy, redact_text, scan_text


def test_scan_text_reports_categories_without_echoing_values():
    report = scan_text(
        "电话 13800138000，身份证 110101199001011234，"
        "邮箱 person@example.com，座机 010-12345678。"
    )

    kinds = {finding.kind for finding in report.findings}
    assert {"mobile", "id_card", "email", "landline"} <= kinds
    assert report.total >= 4
    assert report.clean is False
    assert "13800138000" not in repr(report)
    assert "person@example.com" not in repr(report)


def test_scan_text_returns_clean_for_normal_chat():
    report = scan_text("今天下雨，记得带伞。")

    assert report.clean is True
    assert report.total == 0
    assert report.as_dict() == {"total": 0, "findings": []}


def test_redact_text_replaces_direct_identifiers_and_counts_spans():
    text, count = redact_text(
        "电话 13800138000，邮箱 person@example.com，座机 010-12345678。"
    )

    assert "13800138000" not in text
    assert "person@example.com" not in text
    assert "010-12345678" not in text
    assert text.count("[已隐藏]") == 3
    assert count == 3


def test_apply_privacy_warn_keeps_text_and_reports_findings():
    text, report = apply_privacy("电话 13800138000", mode="warn")

    assert text == "电话 13800138000"
    assert report.total >= 1


def test_apply_privacy_redact_changes_text():
    text, report = apply_privacy("电话 13800138000", mode="redact")

    assert "13800138000" not in text
    assert "[已隐藏]" in text
    assert report.total >= 1


def test_apply_privacy_block_raises_safe_error():
    with pytest.raises(PrivacyError) as caught:
        apply_privacy("电话 13800138000", mode="block", label="导出")

    error = caught.value
    assert error.error_code == "E_PRIVACY"
    assert "13800138000" not in str(error)
    assert "导出" in str(error)


def test_apply_privacy_rejects_unknown_mode():
    with pytest.raises(ValueError):
        apply_privacy("正常文本", mode="unknown")  # type: ignore[arg-type]
