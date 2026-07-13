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
    assert "Move-Item" in text
    assert "[System.IO.File]::Replace" in text
    assert "Test-Path $FinalPath" in text
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
    assert "[System.Int64]" in text
    assert "Get-ChildItem Env:" not in text


def test_actions_check_state_before_material_work():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "Assert-Phase0CanTransition" in text
    assert text.index("-NewState 'PREPARED'") < text.index("$lock = Get-Phase0SupplyLock")
    assert text.index("-NewState 'SELF_TEST_PASSED'") < text.index("& \"$root\\runtime\\python\\python.exe\"")


def test_package_verification_is_closed_over_exact_safe_file_set():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "SHA256SUMS.txt" in text
    assert "Get-FileHash" in text
    assert "-Algorithm SHA256" in text
    assert "duplicate SHA256SUMS path" in text
    assert "malformed SHA256SUMS entry" in text
    assert "SHA256SUMS file set mismatch" in text
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
