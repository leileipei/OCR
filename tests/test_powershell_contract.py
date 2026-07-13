import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
ENTRY = ROOT / "scripts/phase0/Start-Phase0Validation.ps1"
PACKAGE = ROOT / "scripts/phase0/Phase0.Package.psm1"


def _runtime_scripts_text():
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "scripts/phase0").glob("*.ps*")
    )


def test_entrypoint_exposes_initial_offline_actions_without_network_access():
    text = ENTRY.read_text(encoding="utf-8")
    for action in ("Preflight", "Prepare", "SelfTest"):
        assert action in text
    runtime_scripts = _runtime_scripts_text().lower()
    for forbidden in (
        "invoke-webrequest",
        "start-bitstransfer",
        "system.net.webclient",
        "curl",
        "wget",
        "pip download",
        "pip install",
    ):
        assert forbidden not in runtime_scripts


def test_entrypoint_resolves_repository_and_release_roots_safely():
    text = ENTRY.read_text(encoding="utf-8")
    assert "[string]$PackageRoot = ''" in text
    assert "$PSScriptRoot" in text
    assert "'..\\..'" in text
    assert "SHA256SUMS.txt" in text
    assert "Resolve-Path" in text
    assert "[string]$PackageRoot = $PSScriptRoot" not in text


def test_package_module_uses_strict_atomic_state_and_refuses_unsafe_ids():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "Set-StrictMode -Version Latest" in text
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "[System.IO.File]::Replace" in text
    assert "Test-Path -LiteralPath $FinalPath" in text
    assert "Refusing to overwrite" in text
    assert "AllowedTransitions" in text
    assert "OCR_READY_E10_PENDING" in text
    assert "attempt" in text.lower()
    assert "Assert-Phase0Identifier" in text
    assert "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$" in text
    assert "GetFullPath" in text
    assert "Assert-Phase0NoReparsePoint" in text
    assert "GetInvalidFileNameChars" in text
    assert "expectedEvidencePrefix" in text
    assert "[Globalization.DateTimeStyles]::RoundtripKind" in text
    assert "Campaign validation IDs must be different" in text
    assert "Interactive validation ID is already bound" in text
    assert "Scheduled validation ID is already bound" in text
    assert "[System.Int64]" in text
    assert "recorded_at_utc" in text
    assert "EndsWith('Z'" in text
    assert "Get-ChildItem Env:" not in text


def test_actions_check_state_before_material_work():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "Assert-Phase0CanTransition" in text
    assert text.index("-NewState 'PREPARED'") < text.index("$lockValue = Get-Phase0SupplyLock")
    assert text.index("-NewState 'SELF_TEST_PASSED'") < text.index("& \"$root\\runtime\\python\\python.exe\"")


def test_runtime_paths_and_attempts_are_reserved_under_campaign_mutex():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "Enter-Phase0CampaignLock" in text
    assert "System.Threading.Mutex" in text
    assert "FileMode]::CreateNew" in text
    assert "Get-Phase0DiskAttemptMaximum" in text
    assert "attempt-reserved.json" in text
    assert "Assert-Phase0RuntimeLeaf" in text
    assert "ValidateSet('Missing', 'MissingOrFile', 'File', 'Directory')" in text
    assert "Assert-Phase0NoReparsePoint" in text
    assert "Refusing to reuse existing attempt" in text


def test_prepare_uses_attempt_staging_and_atomic_campaign_publish():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "umi-staging" in text
    assert "failed-published-umi" in text
    assert "orphaned-umi" in text
    assert "[System.IO.Directory]::Move" in text
    assert "Remove-Phase0OwnedDirectory" in text
    assert text.index("$attempt = Get-Phase0ActionAttempt") < text.index("& $UmiAsset -y \"-o$UmiRoot\"")


def test_package_verification_is_closed_over_exact_safe_file_set():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "SHA256SUMS.txt" in text
    assert "Get-FileHash" in text
    assert "-Algorithm SHA256" in text
    assert "duplicate SHA256SUMS path" in text
    assert "malformed SHA256SUMS entry" in text
    assert "SHA256SUMS file set mismatch" in text
    assert "Runtime work path must be a normal directory" in text
    assert "work" in text
    assert "[System.IO.Path]::IsPathRooted" in text
    assert "GetFullPath" in text
    assert "StartsWith" in text
    assert "Get-ChildItem -LiteralPath $root -Recurse" not in text


def test_preflight_checks_required_windows_constraints():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "Win32_OperatingSystem" in text
    assert "ProductType" in text
    assert "[Environment]::Is64BitOperatingSystem" in text
    assert "[Environment]::Is64BitProcess" in text
    assert "$PSVersionTable.PSVersion" in text
    assert "WindowsPrincipal" in text
    assert "WindowsBuiltInRole" in text
    assert "5GB" in text
    assert "Test-Phase0Package" in text
    assert "preflight.json" in text
    assert "control characters" in text


def test_prepare_rechecks_locked_umi_and_exact_rapid_layout():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "offline-package.lock.json" in text
    assert "vendor" in text
    assert "& $UmiAsset -y \"-o$UmiRoot\"" in text
    for field in ("runtime_python", "plugin_root", "plugin_name"):
        assert field in text
    for expected in (
        "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/runtime/python.exe",
        "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/plugins",
        "win7_x64_RapidOCR-json",
    ):
        assert expected in text
    assert "run-context.json" in text


def test_selftest_uses_only_the_bundled_python_runtime():
    text = PACKAGE.read_text(encoding="utf-8")
    assert 'runtime\\python\\python.exe' in text
    assert '-m pytest' in text
    assert 'toolkit\\tests' in text
    assert "Portable self-test failed" in text
    assert "$LASTEXITCODE" in text


def test_failure_diagnostics_are_minimal_and_attempt_scoped():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "Write-Phase0Failure" in text
    for allowed in (
        "exception_type",
        "script_stack_trace",
        "windows_version",
        "powershell_version",
        "process_id",
        "SESSIONNAME",
    ):
        assert allowed in text
    for forbidden in ("CommandLine", "Get-Credential", "sample_content"):
        assert forbidden not in text


def test_entrypoint_preserves_the_original_action_error_during_diagnostics():
    text = ENTRY.read_text(encoding="utf-8")
    assert "$originalError = $_" in text
    assert "-ErrorRecord $originalError" in text
    assert "Write-Error -ErrorRecord $originalError" in text


def test_entrypoint_controls_initialization_and_returns_stable_failure():
    text = ENTRY.read_text(encoding="utf-8")
    assert text.index("try {") < text.index("Resolve-Path")
    assert text.index("try {") < text.index("Import-Module")
    assert "$exitCode = 1" in text
    assert "exit $exitCode" in text
    assert "$moduleImported" in text


def test_runtime_path_guards_on_windows_when_powershell_is_available(tmp_path):
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if os.name != "nt" or not pwsh:
        pytest.skip("Windows PowerShell junction behavior requires a Windows host")

    bracket_root = tmp_path / "package[root]"
    bracket_root.mkdir()
    script = (
        f"Import-Module '{PACKAGE}' -Force; "
        f"$lock = Enter-Phase0CampaignLock -PackageRoot '{bracket_root}' -CampaignId campaign-safe; "
        "try { $a = Get-Phase0AttemptContext -PackageRoot '"
        f"{bracket_root}' -CampaignId campaign-safe; "
        "$b = Get-Phase0AttemptContext -PackageRoot '"
        f"{bracket_root}' -CampaignId campaign-safe; "
        "if ($a.number -eq $b.number) { throw 'attempt reused' } } "
        "finally { Exit-Phase0CampaignLock -Lock $lock }"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_attempt_reservation_rejects_windows_junction(tmp_path):
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if os.name != "nt" or not pwsh:
        pytest.skip("Windows junction behavior requires a Windows host")
    package_root = tmp_path / "package"
    attempts = package_root / "work/campaigns/campaign-junction/attempts"
    attempts.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(attempts), str(outside)],
        capture_output=True,
        check=False,
        text=True,
    )
    if linked.returncode != 0:
        pytest.skip("The Windows test account cannot create a junction")
    command = (
        f"Import-Module '{PACKAGE}' -Force; "
        f"Get-Phase0AttemptContext -PackageRoot '{package_root}' "
        "-CampaignId campaign-junction"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode != 0
    assert not any(outside.iterdir())


def test_parallel_attempt_reservations_are_distinct_on_windows(tmp_path):
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if os.name != "nt" or not pwsh:
        pytest.skip("Cross-process mutex behavior requires a Windows host")
    package_root = tmp_path / "parallel[root]"
    package_root.mkdir()
    command = (
        f"Import-Module '{PACKAGE}' -Force; "
        f"$a = Get-Phase0AttemptContext -PackageRoot '{package_root}' "
        "-CampaignId campaign-parallel; [Console]::Out.WriteLine($a.number)"
    )
    processes = [
        subprocess.Popen(
            [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    completed = [process.communicate(timeout=45) for process in processes]
    assert all(process.returncode == 0 for process in processes), completed
    assert sorted(int(stdout.strip()) for stdout, _ in completed) == [1, 2]


def test_module_imports_when_powershell_core_is_available():
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core is not installed on this development host")
    result = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Import-Module '{PACKAGE}' -Force; "
            "@(Get-Command -Module Phase0.Package).Name -join ','",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    for name in (
        "Test-Phase0Package",
        "Invoke-Phase0Preflight",
        "Invoke-Phase0Prepare",
        "Invoke-Phase0SelfTest",
        "Get-Phase0State",
        "Set-Phase0State",
        "Write-Phase0Failure",
    ):
        assert name in result.stdout
