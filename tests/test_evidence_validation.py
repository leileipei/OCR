import json
import os

import pytest

import umi_web_spike.evidence_validation as evidence_validation_module
from tests.evidence_fixtures import write_evidence
from umi_web_spike.evidence_validation import validate_ocr_evidence


def _symlink_or_skip(link, target, target_is_directory=False):
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable")


def test_reusable_validator_accepts_same_evidence_as_full_report(tmp_path):
    write_evidence(
        tmp_path,
        validation_id="run-scheduled-20260713",
        execution_mode="scheduled",
    )

    validation = validate_ocr_evidence(tmp_path, expected_mode="scheduled")

    assert validation.ok is True
    assert validation.validation_id == "run-scheduled-20260713"
    assert validation.campaign_id == "campaign-20260713-001"
    assert validation.summary["processed_pages"] == 100
    assert validation.summary["execution_mode"] == "scheduled"


def test_validator_rejects_results_directory_symlink_to_external_tree(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    write_evidence(
        outside,
        validation_id="run-scheduled-20260713",
        execution_mode="scheduled",
    )
    alias = tmp_path / "results-alias"
    _symlink_or_skip(alias, outside, target_is_directory=True)

    validation = validate_ocr_evidence(alias, expected_mode="scheduled")

    assert validation.ok is False
    assert set(validation.errors) == {"image", "pdf", "resources", "manifest"}
    assert any(
        "symlink" in message or "reparse" in message
        for messages in validation.errors.values()
        for message in messages
    )


def test_validator_rejects_evidence_leaf_symlink_to_external_file(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    write_evidence(
        results,
        validation_id="run-scheduled-20260713",
        execution_mode="scheduled",
    )
    outside = tmp_path / "outside-ocr-image.json"
    outside.write_bytes((results / "ocr-image.json").read_bytes())
    os.unlink(results / "ocr-image.json")
    _symlink_or_skip(results / "ocr-image.json", outside)

    validation = validate_ocr_evidence(results, expected_mode="scheduled")

    assert validation.ok is False
    assert any(
        "symlink" in message or "reparse" in message
        for messages in validation.errors.values()
        for message in messages
    )


def test_reusable_validator_rejects_tampered_manifest(tmp_path):
    write_evidence(
        tmp_path,
        validation_id="run-scheduled-20260713",
        execution_mode="scheduled",
    )
    (tmp_path / "ocr-image.json").write_text("{}", encoding="utf-8")

    validation = validate_ocr_evidence(tmp_path, expected_mode="scheduled")

    assert validation.ok is False
    assert any("SHA-256" in item for item in validation.errors["manifest"])


def test_interactive_and_scheduled_session_rules_are_distinct(tmp_path):
    write_evidence(
        tmp_path,
        validation_id="run-interactive-20260713",
        execution_mode="interactive",
    )

    assert validate_ocr_evidence(tmp_path, expected_mode="interactive").ok is True
    assert validate_ocr_evidence(tmp_path, expected_mode="scheduled").ok is False


def test_validator_rejects_unknown_expected_mode(tmp_path):
    with pytest.raises(ValueError, match="expected_mode"):
        validate_ocr_evidence(tmp_path, expected_mode="service")


def test_validator_requires_execution_mode_on_all_four_envelopes(tmp_path):
    for source in (
        "ocr-image.json",
        "ocr-pdf.json",
        "resources.json",
        "manifest.json",
    ):
        root = tmp_path / source.replace(".json", "")
        root.mkdir()
        write_evidence(
            root,
            validation_id="run-scheduled-20260713",
            execution_mode="scheduled",
            mutate=lambda evidence, source=source: evidence[source].pop(
                "execution_mode"
            ),
        )

        validation = validate_ocr_evidence(root, expected_mode="scheduled")

        assert validation.ok is False
        assert any(
            "execution_mode" in message
            for messages in validation.errors.values()
            for message in messages
        )


@pytest.mark.parametrize(
    ("source", "campaign_value"),
    [
        (source, campaign_value)
        for source in (
            "ocr-image.json",
            "ocr-pdf.json",
            "resources.json",
            "manifest.json",
        )
        for campaign_value in ("campaign-other-20260713", None)
    ],
)
def test_validator_requires_one_campaign_id_on_all_four_envelopes(
    tmp_path, source, campaign_value
):
    def mutate(evidence):
        if campaign_value is None:
            evidence[source].pop("campaign_id")
        else:
            evidence[source]["campaign_id"] = campaign_value

    write_evidence(
        tmp_path,
        validation_id="run-scheduled-20260713",
        execution_mode="scheduled",
        mutate=mutate,
    )

    validation = validate_ocr_evidence(tmp_path, expected_mode="scheduled")

    assert validation.ok is False
    assert validation.campaign_id is None
    assert any(
        "campaign_id" in message
        for messages in validation.errors.values()
        for message in messages
    )

def test_validator_summary_does_not_leak_paths_or_ocr_text(tmp_path):
    evidence = write_evidence(
        tmp_path,
        validation_id="run-scheduled-20260713",
        execution_mode="scheduled",
    )

    validation = validate_ocr_evidence(tmp_path, expected_mode="scheduled")

    serialized = json.dumps(validation.summary, ensure_ascii=False)
    assert validation.ok is True
    assert "campaign_id" not in validation.summary
    assert set(validation.summary) == {
        "execution_mode",
        "windows_session_id",
        "processed_pages",
        "duration_seconds",
        "pages_per_minute",
        "observed_peak_process_tree_rss_bytes",
        "recommended_workers",
        "sample_categories",
        "headless",
    }
    assert "识别文本" not in serialized
    for item in evidence["ocr-image.json"]["details"]["samples"]:
        assert item["path"] not in serialized


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [("category", ["simplified_chinese_image"]), ("path", None)],
)
def test_validator_aggregates_malformed_sample_types(tmp_path, field, bad_value):
    def mutate(evidence):
        evidence["ocr-image.json"]["details"]["samples"][0][field] = bad_value

    write_evidence(
        tmp_path,
        validation_id="run-scheduled-20260713",
        execution_mode="scheduled",
        mutate=mutate,
    )

    validation = validate_ocr_evidence(tmp_path, expected_mode="scheduled")

    assert validation.ok is False
    assert validation.errors["image"]


def test_validator_aggregates_sample_hash_read_errors(tmp_path, monkeypatch):
    write_evidence(
        tmp_path,
        validation_id="run-scheduled-20260713",
        execution_mode="scheduled",
    )
    real_sha256_file = evidence_validation_module.sha256_file

    def fail_sample_hash(path):
        if path.parent.name == "inputs" and path.name != "e10-official.pdf":
            raise OSError("access denied")
        return real_sha256_file(path)

    monkeypatch.setattr(
        evidence_validation_module, "sha256_file", fail_sample_hash
    )

    validation = validate_ocr_evidence(tmp_path, expected_mode="scheduled")

    assert validation.ok is False
    assert any("读取" in message for message in validation.errors["image"])


@pytest.mark.parametrize(
    "qt_processes",
    [pytest.param(None, id="missing"), "4321", ["4321"]],
)
def test_validator_requires_empty_qt_process_array(tmp_path, qt_processes):
    def mutate(evidence):
        details = evidence["resources.json"]["details"]
        if qt_processes is None:
            details.pop("qt_processes")
        else:
            details["qt_processes"] = qt_processes

    write_evidence(
        tmp_path,
        validation_id="run-scheduled-20260713",
        execution_mode="scheduled",
        mutate=mutate,
    )

    validation = validate_ocr_evidence(tmp_path, expected_mode="scheduled")

    assert validation.ok is False
    assert any(
        "qt_processes" in message for message in validation.errors["resources"]
    )
