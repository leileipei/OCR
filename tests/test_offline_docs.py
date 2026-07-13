import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
ENTRY = ROOT / "scripts/phase0/Start-Phase0Validation.ps1"
RUNBOOK = ROOT / "docs/validation/offline-package-runbook.md"


EXPECTED_SAMPLES = [
    ("simplified_chinese_image", r"C:\Phase0Samples\zh.png"),
    ("mixed_chinese_english_image", r"C:\Phase0Samples\mixed.png"),
    ("scanned_pdf_rotated_blank", r"C:\Phase0Samples\scan-100.pdf"),
    ("native_text_pdf", r"C:\Phase0Samples\native.pdf"),
    ("corrupt_pdf", r"C:\Phase0Samples\corrupt.pdf"),
    ("encrypted_pdf", r"C:\Phase0Samples\encrypted.pdf"),
]


def _read_json(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _powershell_commands(text):
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(r".\Start-Phase0Validation.ps1")
    ]


def test_sample_template_contains_each_category_once_and_no_real_paths():
    value = _read_json("templates/samples.json")
    assert list(value) == ["samples"]
    assert [tuple((item["category"], item["path"])) for item in value["samples"]] == EXPECTED_SAMPLES
    assert all(set(item) == {"category", "path"} for item in value["samples"])


def test_rapid_templates_match_official_v215_api_contract():
    assert _read_json("templates/global-options.json") == {"numThread": 4}
    assert _read_json("templates/local-options.json") == {
        "language": "简体中文",
        "angle": True,
        "maxSideLen": 2048,
    }


def test_templates_do_not_contain_secrets_or_oa_addresses():
    text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "templates/samples.json",
            "templates/global-options.json",
            "templates/local-options.json",
        )
    ).lower()
    for forbidden in (
        "password",
        "passwd",
        "token",
        "cookie",
        "authorization",
        "secret",
        "http://",
        "https://",
        "ecology",
        "e-cology",
    ):
        assert forbidden not in text


def test_runbook_commands_match_entrypoint_actions_and_parameters():
    text = RUNBOOK.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    commands = _powershell_commands(text)
    expected_actions = [
        "Preflight",
        "Prepare",
        "SelfTest",
        "RunInteractive",
        "InstallScheduledTask",
        "CollectScheduledTask",
        "ExportEvidence",
        "ResumeE10",
        "BuildFinalReport",
        "RemoveScheduledTask",
    ]
    assert [re.search(r"-Action\s+(\w+)", command).group(1) for command in commands] == expected_actions
    for action in expected_actions:
        assert "'{}'".format(action) in entry
    for parameter in (
        "CampaignId",
        "ValidationId",
        "InteractiveId",
        "ScheduledId",
        "E10EvidencePath",
        "ScheduledResultsDir",
        "FinalReportPath",
        "ConfirmCleanup",
    ):
        if any("-{} ".format(parameter) in command or command.endswith("-{}".format(parameter)) for command in commands):
            assert re.search(r"\$" + parameter + r"\b", entry)


def test_runbook_keeps_e10_as_a_hard_gate_and_requires_local_cleanup():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "OCR_READY_E10_PENDING" in text
    assert "不是完整 Phase 0 通过" in text
    assert "BuildFinalReport" in text
    assert "预期 exit 1" in text
    assert "ResumeE10" in text
    assert "不得" in text and "GitHub" in text
    assert all(word in text for word in ("工作目录", "证据 ZIP", "样本"))
    assert "-ConfirmCleanup" in text
    assert "审核证据后" in text


def test_entrypoint_exports_readiness_and_preserves_final_report_exit_code():
    text = ENTRY.read_text(encoding="utf-8")
    assert "build-ocr-readiness" in text
    assert "export-review-bundle" in text
    assert "E10Evidence.from_dict" in text
    assert "-NewState 'OCR_READY_E10_PENDING'" in text
    assert "-NewState 'E10_READY'" in text
    assert "-NewState 'PHASE_0_PASSED'" in text
    assert "--results-dir $ScheduledResultsDir --e10 $E10EvidencePath --output $FinalReportPath" in text
    assert "$nativeExitCode = [int]$LASTEXITCODE" in text
    assert "exit $nativeExitCode" in text


def test_entrypoint_binds_e10_to_scheduled_evidence_and_resume_snapshot():
    text = ENTRY.read_text(encoding="utf-8")
    assert "$state.scheduled_validation_id -ne $ScheduledId" in text
    assert "evidence.validation_id != sys.argv[3]" in text
    assert "Scheduled OCR results: $scheduledResults" in text
    assert "$recordedE10Evidence" in text
    assert "Get-FileHash -LiteralPath $E10EvidencePath -Algorithm SHA256" in text
    assert "Get-FileHash -LiteralPath $recordedE10Evidence -Algorithm SHA256" in text
    assert "E10 evidence changed after ResumeE10" in text


def _read_workflow(name):
    return (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


def test_workflows_pin_official_actions_and_test_all_supported_hosts():
    test = _read_workflow("test.yml")
    build = _read_workflow("build-offline-package.yml")
    checkout = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
    setup = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
    upload = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
    assert checkout in test and checkout in build
    assert setup in test and setup in build
    assert upload in build
    for workflow in (test, build):
        uses = re.findall(r"(?m)^\s+- uses: ([^\s]+)$", workflow)
        assert uses
        assert all(re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", value) for value in uses)
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in test
    assert "fail-fast: false" in test
    assert "python-version: '3.12.10'" in test and "python-version: '3.12.10'" in build


def test_test_workflow_has_bounded_read_only_windows_and_grammar_checks():
    text = _read_workflow("test.yml")
    assert "permissions:\n  contents: read" in text
    assert "timeout-minutes:" in text
    assert "concurrency:" in text
    assert "cancel-in-progress: true" in text
    assert "[System.Management.Automation.Language.Parser]::ParseFile" in text
    assert "test_task_definition_dry_run_on_windows_without_registration" in text
    assert "if: runner.os == 'Windows'" in text
    assert "feature_version=(3,8)" in text
    assert "python -m pytest -q" in text
    assert "branches: [main, codex/umi-ocr-web-phase0]" in text


def test_build_workflow_is_bounded_and_retests_the_real_archive_without_skips():
    text = _read_workflow("build-offline-package.yml")
    assert re.search(r"(?m)^on:\n  workflow_dispatch:\n  push:\n    tags:\n      - 'offline-v\*'$", text)
    assert "pull_request:" not in text
    assert "branches:" not in text
    assert "runs-on: windows-latest" in text
    assert "permissions:\n  contents: read" in text
    assert "timeout-minutes:" in text
    assert "concurrency:" in text
    full_test = text.index("python -m pytest -q")
    build = text.index("scripts/build-offline-package.ps1")
    product_test = text.index("BUILT_OFFLINE_PACKAGE")
    assert full_test < build < product_test
    assert "tests/test_offline_package.py" in text
    assert "skipped" in text


def test_build_workflow_artifact_is_an_exact_publication_allowlist():
    text = _read_workflow("build-offline-package.yml")
    path_block = re.search(
        r"(?ms)^          path: \|\n(?P<paths>(?:            [^\n]+\n)+)"
        r"          if-no-files-found: error$",
        text,
    )
    assert path_block is not None
    paths = [line.strip() for line in path_block.group("paths").splitlines()]
    assert paths == [
        "dist/umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip",
        "dist/umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip.sha256",
        "dist/sbom.json",
        "dist/THIRD_PARTY_NOTICES.txt",
        "docs/validation/README-release.md",
    ]
    assert "retention-days: 14" in text
    assert "downloads/" not in text
    assert "work/" not in text
    assert "*" not in "\n".join(paths)
