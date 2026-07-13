import json

import pytest

from umi_web_spike.cli import main
from umi_web_spike.report import build_report


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_valid_evidence(tmp_path):
    evidence = {
        "e10.json": {"ready": True},
        "ocr-image.json": {"ok": True},
        "ocr-pdf.json": {
            "ok": True,
            "details": {"searchable_text": True},
        },
        "resources.json": {
            "ok": True,
            "details": {"headless": True},
        },
    }
    for name, value in evidence.items():
        _write(tmp_path / name, value)
    return evidence


def test_report_passes_only_when_all_gates_are_boolean_true(tmp_path):
    _write_valid_evidence(tmp_path)

    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is True

    text = report.read_text(encoding="utf-8")
    assert "结论：继续阶段 1" in text
    assert text.count("- [x]") == 6
    for name in ("e10.json", "ocr-image.json", "ocr-pdf.json", "resources.json"):
        assert str(tmp_path / name) in text


def test_report_stops_when_headless_execution_fails(tmp_path):
    _write_valid_evidence(tmp_path)
    _write(
        tmp_path / "resources.json",
        {"ok": True, "details": {"headless": False}},
    )

    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is False
    assert "结论：停止" in report.read_text(encoding="utf-8")


def test_missing_file_safely_generates_diagnostic_stop_report(tmp_path):
    _write_valid_evidence(tmp_path)
    (tmp_path / "ocr-image.json").unlink()

    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is False
    text = report.read_text(encoding="utf-8")
    assert "ocr-image.json" in text
    assert "文件不存在" in text
    assert "结论：停止" in text


def test_invalid_json_safely_generates_diagnostic_stop_report(tmp_path):
    _write_valid_evidence(tmp_path)
    (tmp_path / "ocr-pdf.json").write_text("{not json", encoding="utf-8")

    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is False
    text = report.read_text(encoding="utf-8")
    assert "JSON 无效" in text
    assert "ocr-pdf.json" in text


def test_non_object_root_safely_generates_diagnostic_stop_report(tmp_path):
    _write_valid_evidence(tmp_path)
    _write(tmp_path / "ocr-image.json", [True])

    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is False
    assert "根节点必须是对象" in report.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("file_name", "value"),
    [
        ("ocr-pdf.json", {"ok": True, "details": "not-an-object"}),
        ("resources.json", {"ok": True, "details": ["not-an-object"]}),
    ],
)
def test_wrong_details_type_safely_generates_diagnostic_stop_report(
    tmp_path, file_name, value
):
    _write_valid_evidence(tmp_path)
    _write(tmp_path / file_name, value)

    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is False
    text = report.read_text(encoding="utf-8")
    assert "details 必须是对象" in text
    assert file_name in text


def test_missing_gate_field_is_diagnosed_and_fails_closed(tmp_path):
    _write_valid_evidence(tmp_path)
    _write(tmp_path / "e10.json", {})

    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is False
    assert "缺少字段：ready" in report.read_text(encoding="utf-8")


@pytest.mark.parametrize("fake_true", ["true", 1])
@pytest.mark.parametrize(
    ("file_name", "field_path"),
    [
        ("e10.json", ("ready",)),
        ("ocr-image.json", ("ok",)),
        ("ocr-pdf.json", ("ok",)),
        ("ocr-pdf.json", ("details", "searchable_text")),
        ("resources.json", ("ok",)),
        ("resources.json", ("details", "headless")),
    ],
)
def test_pseudo_boolean_never_passes_a_gate(
    tmp_path, fake_true, file_name, field_path
):
    evidence = _write_valid_evidence(tmp_path)
    target = evidence[file_name]
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = fake_true
    _write(tmp_path / file_name, evidence[file_name])

    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is False
    text = report.read_text(encoding="utf-8")
    assert "必须是布尔 true" in text
    assert "结论：停止" in text


def _report_cli_args(tmp_path, output):
    return [
        "build-report",
        "--results-dir",
        str(tmp_path),
        "--e10",
        str(tmp_path / "e10.json"),
        "--output",
        str(output),
    ]


def test_build_report_cli_returns_zero_for_pass(tmp_path):
    _write_valid_evidence(tmp_path)
    assert main(_report_cli_args(tmp_path, tmp_path / "pass.md")) == 0


def test_build_report_cli_returns_one_for_stop(tmp_path):
    _write_valid_evidence(tmp_path)
    _write(tmp_path / "e10.json", {"ready": False})
    assert main(_report_cli_args(tmp_path, tmp_path / "stop.md")) == 1


def test_build_report_cli_help_lists_required_options(capsys):
    with pytest.raises(SystemExit) as error:
        main(["build-report", "--help"])

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "--results-dir" in output
    assert "--e10" in output
    assert "--output" in output
