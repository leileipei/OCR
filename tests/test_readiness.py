import hashlib
import json
import zipfile
from dataclasses import replace

import pytest

import umi_web_spike.evidence_validation as evidence_validation_module
from tests.evidence_fixtures import write_evidence
from umi_web_spike.cli import main
from umi_web_spike.readiness import (
    build_ocr_readiness_report,
    export_review_bundle,
)


def _write_pair(
    tmp_path,
    campaign_id="campaign-20260713-001",
    interactive_id="run-interactive-20260713",
    scheduled_id="run-scheduled-20260713",
):
    interactive = tmp_path / "interactive"
    scheduled = tmp_path / "scheduled"
    interactive.mkdir(parents=True)
    scheduled.mkdir(parents=True)
    write_evidence(
        interactive,
        validation_id=interactive_id,
        execution_mode="interactive",
        campaign_id=campaign_id,
    )
    write_evidence(
        scheduled,
        validation_id=scheduled_id,
        execution_mode="scheduled",
        campaign_id=campaign_id,
    )
    return interactive, scheduled


def test_readiness_requires_distinct_interactive_and_scheduled_runs(tmp_path):
    interactive, scheduled = _write_pair(tmp_path)
    report = tmp_path / "ocr-readiness.md"

    assert (
        build_ocr_readiness_report(
            "campaign-20260713-001", interactive, scheduled, report
        )
        is True
    )

    text = report.read_text(encoding="utf-8")
    assert "campaign-20260713-001" in text
    assert "run-interactive-20260713" in text
    assert "run-scheduled-20260713" in text
    assert "OCR_READY_E10_PENDING" in text
    assert "PHASE_0_PASSED" not in text
    assert "Phase 0 尚未通过" in text


def test_readiness_rejects_same_validation_id_without_output(tmp_path):
    interactive, scheduled = _write_pair(tmp_path)
    scheduled_manifest = json.loads(
        (scheduled / "manifest.json").read_text(encoding="utf-8")
    )
    for name in (
        "ocr-image.json",
        "ocr-pdf.json",
        "resources.json",
        "manifest.json",
    ):
        path = scheduled / name
        value = json.loads(path.read_text(encoding="utf-8"))
        value["validation_id"] = "run-interactive-20260713"
        path.write_text(json.dumps(value), encoding="utf-8")
    scheduled_manifest = json.loads(
        (scheduled / "manifest.json").read_text(encoding="utf-8")
    )
    scheduled_manifest["evidence"] = {
        name: evidence_validation_module.sha256_file(scheduled / name)
        for name in ("ocr-image.json", "ocr-pdf.json", "resources.json")
    }
    (scheduled / "manifest.json").write_text(
        json.dumps(scheduled_manifest), encoding="utf-8"
    )
    report = tmp_path / "ocr-readiness.md"

    with pytest.raises(ValueError, match="different validation IDs"):
        build_ocr_readiness_report(
            "campaign-20260713-001", interactive, scheduled, report
        )

    assert not report.exists()


def test_readiness_rejects_two_valid_runs_from_different_campaigns(tmp_path):
    interactive, _ = _write_pair(tmp_path / "first", campaign_id="campaign-first-20260713")
    _, scheduled = _write_pair(
        tmp_path / "second", campaign_id="campaign-second-20260713"
    )
    assert evidence_validation_module.validate_ocr_evidence(
        interactive, expected_mode="interactive"
    ).ok is True
    assert evidence_validation_module.validate_ocr_evidence(
        scheduled, expected_mode="scheduled"
    ).ok is True
    output = tmp_path / "review.zip"

    with pytest.raises(ValueError, match="campaign"):
        export_review_bundle(
            "campaign-first-20260713", interactive, scheduled, output
        )

    assert not output.exists()


@pytest.mark.parametrize(
    ("context", "reserved_id"),
    [
        (context, "safe-{}-suffix".format(status))
        for context in ("campaign", "interactive", "scheduled")
        for status in (
            "PhAsE_0_PaSsEd",
            "OcR_ReAdY_E10_PeNdInG",
            "PhAsE_0_NoT_PaSsEd",
        )
    ],
)
def test_readiness_rejects_reserved_status_words_in_all_ids(
    tmp_path, context, reserved_id
):
    values = {
        "campaign_id": "campaign-20260713-001",
        "interactive_id": "run-interactive-20260713",
        "scheduled_id": "run-scheduled-20260713",
    }
    values["{}_id".format(context)] = reserved_id
    interactive, scheduled = _write_pair(tmp_path, **values)
    output = tmp_path / "ocr-readiness.md"

    with pytest.raises(ValueError, match="reserved status"):
        build_ocr_readiness_report(
            values["campaign_id"], interactive, scheduled, output
        )

    assert not output.exists()


@pytest.mark.parametrize("campaign_id", ["bad", "含中文的活动编号", "../../secret"])
def test_readiness_rejects_invalid_campaign_id(tmp_path, campaign_id):
    interactive, scheduled = _write_pair(tmp_path)
    report = tmp_path / "ocr-readiness.md"

    with pytest.raises(ValueError):
        build_ocr_readiness_report(campaign_id, interactive, scheduled, report)

    assert not report.exists()


@pytest.mark.parametrize(
    ("damaged_mode", "damaged_file"),
    [("interactive", "ocr-image.json"), ("scheduled", "ocr-pdf.json")],
)
def test_review_bundle_rejects_failed_evidence_without_artifacts(
    tmp_path, damaged_mode, damaged_file
):
    interactive, scheduled = _write_pair(tmp_path)
    damaged = interactive if damaged_mode == "interactive" else scheduled
    (damaged / damaged_file).write_text("{}", encoding="utf-8")
    output = tmp_path / "review.zip"

    with pytest.raises(ValueError, match=damaged_mode):
        export_review_bundle(
            "campaign-20260713-001", interactive, scheduled, output
        )

    assert not output.exists()
    assert not list(tmp_path.glob("*.staging"))


def test_review_bundle_contains_only_deterministic_allowlisted_summary(tmp_path):
    interactive, scheduled = _write_pair(tmp_path)

    first = export_review_bundle(
        "campaign-20260713-001", interactive, scheduled, tmp_path / "review-1.zip"
    )
    second = export_review_bundle(
        "campaign-20260713-001", interactive, scheduled, tmp_path / "review-2.zip"
    )

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        payload = "\n".join(
            archive.read(name).decode("utf-8") for name in names
        )
        summary = json.loads(archive.read("review-summary.json"))
        checksum_lines = archive.read("SHA256SUMS.txt").decode("utf-8").splitlines()
        archived_payloads = {
            name: archive.read(name)
            for name in ("review-summary.json", "ocr-readiness.md")
        }
    assert names == [
        "review-summary.json",
        "ocr-readiness.md",
        "SHA256SUMS.txt",
    ]
    assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos)
    assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in infos)
    assert all(info.create_system == 3 for info in infos)
    assert all(info.external_attr == 0o100644 << 16 for info in infos)
    checksums = dict(line.split("  ", 1)[::-1] for line in checksum_lines)
    assert set(checksums) == {"review-summary.json", "ocr-readiness.md"}
    for name, digest in checksums.items():
        assert digest == hashlib.sha256(archived_payloads[name]).hexdigest()
    assert set(summary) == {
        "schema_version",
        "campaign_id",
        "status",
        "interactive",
        "scheduled",
    }
    assert summary["interactive"]["validation_id"] == "run-interactive-20260713"
    assert summary["scheduled"]["validation_id"] == "run-scheduled-20260713"
    assert "ocr_text" not in payload.lower()
    assert "official_document_path" not in payload.lower()
    assert str(tmp_path) not in payload
    assert "识别文本" not in payload
    assert "OCR English" not in payload


@pytest.mark.parametrize(
    "sensitive_key",
    ["password", "access_token", "cookie", "authorization", "ocr_text", "input_path"],
)
def test_review_bundle_recursively_rejects_sensitive_summary_keys(
    tmp_path, monkeypatch, sensitive_key
):
    interactive, scheduled = _write_pair(tmp_path)
    real_validate = evidence_validation_module.validate_ocr_evidence

    def malicious_validate(results_dir, expected_mode):
        result = real_validate(results_dir, expected_mode)
        return replace(
            result,
            summary={**result.summary, "nested": [{sensitive_key: "secret"}]},
        )

    monkeypatch.setattr(
        "umi_web_spike.readiness.validate_ocr_evidence", malicious_validate
    )
    output = tmp_path / "review.zip"

    expected_path = "$.interactive.nested[0].{}".format(sensitive_key)
    with pytest.raises(ValueError, match="sensitive") as captured:
        export_review_bundle(
            "campaign-20260713-001", interactive, scheduled, output
        )

    assert expected_path in str(captured.value)
    assert "secret" not in str(captured.value)
    assert not output.exists()
    assert not list(tmp_path.glob("*.staging"))


@pytest.mark.parametrize("leaked_value", ["C:\\Secret\\document.pdf", "绝密 OCR 识别文本"])
def test_review_bundle_rejects_path_or_ocr_text_in_summary_values(
    tmp_path, monkeypatch, leaked_value
):
    interactive, scheduled = _write_pair(tmp_path)
    real_validate = evidence_validation_module.validate_ocr_evidence

    def malicious_validate(results_dir, expected_mode):
        result = real_validate(results_dir, expected_mode)
        return replace(result, summary={**result.summary, "sample_categories": [leaked_value]})

    monkeypatch.setattr(
        "umi_web_spike.readiness.validate_ocr_evidence", malicious_validate
    )
    output = tmp_path / "review.zip"

    with pytest.raises(ValueError, match="sample_categories"):
        export_review_bundle(
            "campaign-20260713-001", interactive, scheduled, output
        )

    assert not output.exists()


def test_review_bundle_write_failure_removes_staging_and_partial_zip(
    tmp_path, monkeypatch
):
    interactive, scheduled = _write_pair(tmp_path)
    output = tmp_path / "review.zip"
    real_writestr = zipfile.ZipFile.writestr
    calls = {"count": 0}

    def fail_second_write(archive, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("disk full")
        return real_writestr(archive, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", fail_second_write)

    with pytest.raises(OSError, match="disk full"):
        export_review_bundle(
            "campaign-20260713-001", interactive, scheduled, output
        )

    assert not output.exists()
    assert not list(tmp_path.glob("*.staging"))


def test_review_bundle_refuses_existing_output_without_modifying_it(tmp_path):
    interactive, scheduled = _write_pair(tmp_path)
    output = tmp_path / "review.zip"
    output.write_bytes(b"existing")

    with pytest.raises(ValueError, match="already exists"):
        export_review_bundle(
            "campaign-20260713-001", interactive, scheduled, output
        )

    assert output.read_bytes() == b"existing"
    assert not list(tmp_path.glob("*.staging"))


def test_readiness_cli_commands_succeed(tmp_path):
    interactive, scheduled = _write_pair(tmp_path)
    report = tmp_path / "ocr-readiness.md"
    bundle = tmp_path / "review.zip"
    common = [
        "--campaign-id",
        "campaign-20260713-001",
        "--interactive-dir",
        str(interactive),
        "--scheduled-dir",
        str(scheduled),
    ]

    assert main(["build-ocr-readiness", *common, "--output", str(report)]) == 0
    assert main(["export-review-bundle", *common, "--output", str(bundle)]) == 0
    assert report.is_file()
    assert bundle.is_file()


@pytest.mark.parametrize("command", ["build-ocr-readiness", "export-review-bundle"])
def test_readiness_cli_returns_one_for_invalid_input_or_existing_output(
    tmp_path, command
):
    interactive, scheduled = _write_pair(tmp_path)
    output = tmp_path / ("review.zip" if command == "export-review-bundle" else "report.md")
    output.write_bytes(b"existing")

    code = main(
        [
            command,
            "--campaign-id",
            "campaign-20260713-001",
            "--interactive-dir",
            str(interactive),
            "--scheduled-dir",
            str(scheduled),
            "--output",
            str(output),
        ]
    )

    assert code == 1
    assert output.read_bytes() == b"existing"
