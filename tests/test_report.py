import json
from copy import deepcopy

import pytest

from umi_web_spike.cli import main
from umi_web_spike.report import build_report


VALIDATION_ID = "run-20260713-001"
COMMON = {
    "schema_version": "1.0",
    "validation_id": VALIDATION_ID,
    "recorded_at_utc": "2026-07-13T04:05:06Z",
}
PLUGIN = {"name": "ocr_paddle", "root": "C:\\Umi-OCR\\data\\plugins"}
INTERPRETER = {"executable": "C:\\Umi-OCR\\runtime\\python.exe", "version": "3.8.10"}
CATEGORIES = {
    "simplified_chinese_image",
    "mixed_chinese_english_image",
    "scanned_pdf_rotated_blank",
    "native_text_pdf",
    "corrupt_pdf",
    "encrypted_pdf",
}


def _sample(category):
    expected = {
        "simplified_chinese_image": "ocr_success",
        "mixed_chinese_english_image": "ocr_success",
        "scanned_pdf_rotated_blank": "ocr_success",
        "native_text_pdf": "native_text_detected",
        "corrupt_pdf": "open_failed",
        "encrypted_pdf": "encrypted_rejected",
    }[category]
    value = {
        "category": category,
        "path": "C:\\samples\\{}.dat".format(category),
        "input_sha256": "a" * 64,
        "expected": expected,
        "actual": expected,
        "ok": True,
    }
    if category in ("simplified_chinese_image", "mixed_chinese_english_image"):
        value.update({"input_nonblank": True, "code": 100, "non_empty_text_blocks": 1})
    elif category == "scanned_pdf_rotated_blank":
        value.update({"source_has_text": False, "pages": 100, "rotated_pages": 1, "blank_pages": 1, "ocr_text": "识别文本", "output_contains_ocr_text": True})
    elif category == "native_text_pdf":
        value["source_has_text"] = True
    elif category == "corrupt_pdf":
        value["error"] = "FileDataError: cannot open broken document"
    elif category == "encrypted_pdf":
        value["needs_pass"] = True
    return value


def _valid_evidence():
    e10 = {
        **COMMON,
        "protocol": "oidc",
        "official_document_reference": "E10 官方统一身份接口文档 v10",
        "official_document_sha256": "b" * 64,
        "login_endpoint": "https://oa.example.internal/sso/authorize",
        "verification_endpoint": "https://oa.example.internal/sso/userinfo",
        "external_user_id_field": "user_id",
        "department_id_field": "department_id",
        "test_login_succeeded": True,
        "disabled_account_rejected": True,
        "logout_behavior_verified": True,
        "ready": True,
    }
    image = {
        **COMMON,
        "plugin": PLUGIN,
        "interpreter": INTERPRETER,
        "ok": True,
        "name": "ocr-image",
        "details": {"samples": [_sample("simplified_chinese_image"), _sample("mixed_chinese_english_image")]},
    }
    pdf = {
        **COMMON,
        "plugin": PLUGIN,
        "interpreter": INTERPRETER,
        "ok": True,
        "name": "ocr-pdf",
        "details": {
            "searchable_text": True,
            "samples": [_sample(category) for category in CATEGORIES if category.endswith("pdf") or category.startswith(("scanned", "native", "corrupt", "encrypted"))],
        },
    }
    resources = {
        **COMMON,
        "plugin": PLUGIN,
        "interpreter": INTERPRETER,
        "ok": True,
        "name": "resources",
        "details": {
            "observed_peak_process_tree_rss_bytes": 1024,
            "process_tree_cpu_seconds": 1.5,
            "duration_seconds": 60.0,
            "processed_pages": 100,
            "minimum_required_pages": 100,
            "pages_per_minute": 100.0,
            "sample_count": 2,
            "recommended_workers": 2,
            "worker_calculation_basis": "memory_budget_bytes // observed_peak_process_tree_rss_bytes",
            "qt_loaded": False,
            "interactive_session": False,
            "headless": True,
        },
    }
    manifest = {**COMMON, "status": "completed", "passed": True, "evidence": ["ocr-image.json", "ocr-pdf.json", "resources.json"]}
    return {"e10.json": e10, "ocr-image.json": image, "ocr-pdf.json": pdf, "resources.json": resources, "manifest.json": manifest}


def _write_evidence(tmp_path, mutate=None):
    evidence = deepcopy(_valid_evidence())
    if mutate:
        mutate(evidence)
    for name, value in evidence.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    return evidence


def test_report_passes_only_complete_consistent_evidence(tmp_path):
    _write_evidence(tmp_path)
    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is True
    assert "结论：继续阶段 1" in report.read_text(encoding="utf-8")


def test_minimal_ready_true_e10_is_rejected_with_diagnostic(tmp_path):
    _write_evidence(tmp_path, lambda evidence: evidence.__setitem__("e10.json", {"ready": True}))
    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is False
    assert "E10" in report.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e["e10.json"].__setitem__("protocol", "shared_cookie"),
        lambda e: e["e10.json"].pop("department_id_field"),
        lambda e: e["e10.json"].__setitem__("disabled_account_rejected", False),
        lambda e: e["e10.json"].__setitem__("ready", "true"),
        lambda e: e["e10.json"].__setitem__("ready", False),
    ],
)
def test_report_revalidates_full_e10_contract(tmp_path, mutation):
    _write_evidence(tmp_path, mutation)
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_report_rejects_consistently_not_ready_e10(tmp_path):
    def mutate(evidence):
        e10 = evidence["e10.json"]
        e10["test_login_succeeded"] = False
        e10["disabled_account_rejected"] = False
        e10["logout_behavior_verified"] = False
        e10["ready"] = False

    _write_evidence(tmp_path, mutate)
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


@pytest.mark.parametrize("source", ["e10.json", "ocr-image.json", "ocr-pdf.json", "resources.json", "manifest.json"])
def test_report_rejects_cross_run_evidence(tmp_path, source):
    _write_evidence(tmp_path, lambda e: e[source].__setitem__("validation_id", "another-run"))
    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is False
    assert "validation_id" in report.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("source", "field", "bad_value"),
    [
        ("ocr-image.json", "schema_version", 1),
        ("ocr-pdf.json", "recorded_at_utc", "yesterday"),
        ("resources.json", "plugin", {"name": "other", "root": "C:\\other"}),
        ("ocr-image.json", "interpreter", {"executable": "", "version": "3.8.10"}),
    ],
)
def test_report_rejects_invalid_or_inconsistent_identity(tmp_path, source, field, bad_value):
    _write_evidence(tmp_path, lambda e: e[source].__setitem__(field, bad_value))
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("observed_peak_process_tree_rss_bytes", 0),
        ("process_tree_cpu_seconds", -1),
        ("duration_seconds", 0),
        ("processed_pages", 99),
        ("pages_per_minute", 0),
        ("sample_count", 0),
        ("recommended_workers", 0),
        ("worker_calculation_basis", ""),
        ("qt_loaded", "false"),
        ("interactive_session", "false"),
    ],
)
def test_report_strictly_validates_resource_metrics(tmp_path, field, bad_value):
    def mutate(evidence):
        evidence["resources.json"]["details"][field] = bad_value

    _write_evidence(tmp_path, mutate)
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_report_rejects_missing_sample_category_or_mismatched_outcome(tmp_path):
    def missing(evidence):
        evidence["ocr-pdf.json"]["details"]["samples"] = evidence["ocr-pdf.json"]["details"]["samples"][:-1]

    _write_evidence(tmp_path, missing)
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "missing.md") is False

    def mismatch(evidence):
        evidence["ocr-image.json"]["details"]["samples"][0]["actual"] = "empty_ocr_text"

    other = tmp_path / "other"
    other.mkdir()
    _write_evidence(other, mismatch)
    assert build_report(other, other / "e10.json", other / "mismatch.md") is False


def test_report_rejects_samples_stored_under_wrong_evidence_type(tmp_path):
    def mutate(evidence):
        image_samples = evidence["ocr-image.json"]["details"]["samples"]
        pdf_samples = evidence["ocr-pdf.json"]["details"]["samples"]
        evidence["ocr-image.json"]["details"]["samples"] = pdf_samples
        evidence["ocr-pdf.json"]["details"]["samples"] = image_samples

    _write_evidence(tmp_path, mutate)
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_report_rejects_blank_positive_image_even_with_ocr_text(tmp_path):
    def mutate(evidence):
        evidence["ocr-image.json"]["details"]["samples"][0]["input_nonblank"] = False

    _write_evidence(tmp_path, mutate)
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_failed_manifest_can_never_pass(tmp_path):
    _write_evidence(tmp_path, lambda evidence: evidence["manifest.json"].__setitem__("status", "failed"))
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_completed_manifest_with_false_passed_cannot_pass(tmp_path):
    _write_evidence(tmp_path, lambda evidence: evidence["manifest.json"].__setitem__("passed", False))
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("plugin", {"name": "ocr_paddle", "root": "relative/plugins"}),
        ("interpreter", {"executable": "python.exe", "version": "3.8.10"}),
    ],
)
def test_report_requires_absolute_plugin_and_interpreter_paths(tmp_path, field, value):
    def mutate(evidence):
        for source in ("ocr-image.json", "ocr-pdf.json", "resources.json"):
            evidence[source][field] = value

    _write_evidence(tmp_path, mutate)
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_build_report_cli_returns_failure_but_still_writes_diagnostic(tmp_path):
    _write_evidence(tmp_path, lambda evidence: evidence["e10.json"].__setitem__("ready", False))
    output = tmp_path / "report.md"
    code = main(["build-report", "--results-dir", str(tmp_path), "--e10", str(tmp_path / "e10.json"), "--output", str(output)])
    assert code == 1
    assert output.exists()
