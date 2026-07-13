import json
from pathlib import Path

import pytest

from tests.evidence_fixtures import write_evidence
from umi_web_spike.cli import main
from umi_web_spike.report import build_report


VALIDATION_ID = "run-20260713-001"
def _write_evidence(tmp_path, mutate=None):
    return write_evidence(
        tmp_path,
        validation_id=VALIDATION_ID,
        execution_mode="scheduled",
        mutate=mutate,
    )


def test_report_passes_only_complete_consistent_evidence(tmp_path):
    _write_evidence(tmp_path)
    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is True
    assert "结论：继续阶段 1" in report.read_text(encoding="utf-8")


def test_full_report_requires_scheduled_ocr_envelopes(tmp_path):
    _write_evidence(
        tmp_path,
        lambda evidence: evidence["ocr-image.json"].__setitem__(
            "execution_mode", "interactive"
        ),
    )

    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False
    assert "execution_mode" in (tmp_path / "report.md").read_text(encoding="utf-8")


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


@pytest.mark.parametrize(
    ("category", "text"),
    [("simplified_chinese_image", "English only"), ("mixed_chinese_english_image", "只有中文"), ("mixed_chinese_english_image", "")],
)
def test_report_recomputes_language_coverage_from_ocr_text(tmp_path, category, text):
    def mutate(evidence):
        sample = next(item for item in evidence["ocr-image.json"]["details"]["samples"] if item["category"] == category)
        sample["ocr_text"] = text

    _write_evidence(tmp_path, mutate)
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_report_rehashes_existing_sample_file(tmp_path):
    evidence = _write_evidence(tmp_path)
    sample_path = Path(evidence["ocr-image.json"]["details"]["samples"][0]["path"])
    sample_path.write_bytes(b"changed after validation")
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_report_rejects_missing_sample_file_even_with_well_formed_digest(tmp_path):
    def mutate(evidence):
        sample = evidence["ocr-image.json"]["details"]["samples"][0]
        sample["path"] = str((tmp_path / "missing.png").resolve())

    _write_evidence(tmp_path, mutate)
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_report_rehashes_controlled_e10_document(tmp_path):
    evidence = _write_evidence(tmp_path)
    Path(evidence["e10.json"]["official_document_path"]).write_bytes(b"replaced document")
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_report_rehashes_manifest_evidence_files(tmp_path):
    _write_evidence(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence"]["ocr-image.json"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("memory_budget_bytes", 3071),
        ("logical_cpu_count", 7),
        ("memory_worker_limit", 3),
        ("cpu_worker_limit", 3),
        ("business_concurrency_limit", 3),
        ("recommended_workers", 3),
        ("pages_per_minute", 99.9),
    ],
)
def test_report_cross_checks_derived_resource_values(tmp_path, field, bad_value):
    def mutate(evidence):
        evidence["resources.json"]["details"][field] = bad_value

    _write_evidence(tmp_path, mutate)
    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False


def test_report_matches_processed_pages_to_scanned_pdf_evidence(tmp_path):
    def mutate(evidence):
        scanned = next(item for item in evidence["ocr-pdf.json"]["details"]["samples"] if item["category"] == "scanned_pdf_rotated_blank")
        scanned["pages"] = 101

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
