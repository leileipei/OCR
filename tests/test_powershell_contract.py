import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
ENTRY = ROOT / "scripts/phase0/Start-Phase0Validation.ps1"
PACKAGE = ROOT / "scripts/phase0/Phase0.Package.psm1"
SCHEDULER = ROOT / "scripts/phase0/Phase0.Scheduler.psm1"
WINDOWS_RUNNER = ROOT / "scripts/run-windows-validation.ps1"


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
    assert "$CampaignId.ToLowerInvariant()" in text
    assert "$writer = $null" in text
    assert "$stream.Dispose()" in text


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


def test_scheduler_uses_unique_name_and_requires_explicit_cleanup():
    text = SCHEDULER.read_text(encoding="utf-8")
    assert "UmiOcrPhase0-$ValidationId" in text
    assert "Get-Credential" in text
    assert "-Password $PlainPassword" in text
    assert "Remove-Phase0ScheduledTask" in text
    assert "[switch]$ConfirmCleanup" in text
    assert "Unregister-ScheduledTask" in text
    assert "-Confirm:$false" in text
    assert "$ConfirmCleanup" in text


def test_scheduler_restricts_argument_file_and_never_persists_credentials():
    text = SCHEDULER.read_text(encoding="utf-8")
    assert "SetAccessRuleProtection($true, $false)" in text
    assert "FileMode]::CreateNew" in text
    assert "FileSystemAccessRule" in text
    assert "LocalSystemSid" in text
    assert "BuiltinAdministratorsSid" in text
    assert "argument_file_relative" in text
    for forbidden in ("plain_password", "command_line"):
        assert forbidden not in text.lower()


def test_scheduler_uses_restricted_directory_atomic_files_and_install_hashes():
    text = SCHEDULER.read_text(encoding="utf-8")
    for required in (
        "DirectorySecurity",
        "SetAccessRuleProtection($true, $false)",
        "SetOwner",
        "$secureRelative/schedule-$ValidationId",
        "FileMode]::CreateNew",
        "Flush($true)",
        "[System.IO.File]::Move",
        "argument_sha256",
        "account_sid",
        "installed_task_xml_sha256",
        "structured_definition",
        "Assert-Phase0RestrictedSchedulePath",
    ):
        assert required in text


def test_runner_revalidates_trusted_relationships_not_only_json_keys():
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    runner = WINDOWS_RUNNER.read_text(encoding="utf-8")
    assert "Read-Phase0TrustedRunnerArguments" in runner
    assert "Assert-Phase0RunnerConfiguration" in scheduler
    for required in (
        "runtime/python/python.exe",
        "Umi-OCR_Rapid_v2.1.5/UmiOCR-data",
        "runtime/python.exe",
        "win7_x64_RapidOCR-json",
        "templates/global-options.json",
        "templates/local-options.json",
        "templates/samples.json",
        "argument_sha256",
        "install-metadata.json",
    ):
        assert required in scheduler
    assert "Resolve-Path -LiteralPath $ArgumentFile" not in runner


def test_install_and_collect_use_distinct_monotonic_attempts_and_retry_states():
    text = SCHEDULER.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    assert "install_attempt" in text
    assert "collection_attempt" in text
    assert "Get-Phase0PendingSchedule" in text
    assert "Only one uncollected scheduled task is allowed per campaign" in text
    assert "'INTERACTIVE_OCR_FAILED'" in text
    assert "'SCHEDULED_OCR_FAILED'" in text
    assert "-Final $false" not in text
    assert "-Passed $false -Final $true" in text
    assert "Get-Phase0AttemptContext" in text
    allocation_clause = entry.split("if ($Action -in", 1)[1].split("switch ($Action)", 1)[0]
    for initial_action in ("Preflight", "Prepare", "SelfTest"):
        assert initial_action in allocation_clause
    for deferred_action in ("RunInteractive", "InstallScheduledTask", "CollectScheduledTask"):
        assert deferred_action not in allocation_clause
    catch_block = entry.split("catch {", 1)[1]
    assert "InstallScheduledTask'  = 'SCHEDULED_OCR_FAILED'" not in catch_block
    assert "CollectScheduledTask'  = 'SCHEDULED_OCR_FAILED'" not in catch_block


def test_scheduler_acl_uses_atomic_mutation_rights_and_protects_attempt_parent():
    text = SCHEDULER.read_text(encoding="utf-8")
    verifier = text.split("function Assert-Phase0RestrictedSchedulePath", 1)[1].split(
        "function New-Phase0RestrictedScheduleDirectory", 1
    )[0]
    assert "FileSystemRights]::Modify" not in verifier
    for right in (
        "WriteData",
        "CreateFiles",
        "AppendData",
        "CreateDirectories",
        "WriteExtendedAttributes",
        "WriteAttributes",
        "Delete",
        "DeleteSubdirectoriesAndFiles",
        "ChangePermissions",
        "TakeOwnership",
    ):
        assert f"FileSystemRights]::{right}" in verifier
    directory_creator = text.split("function New-Phase0RestrictedScheduleDirectory", 1)[1].split(
        "function Write-Phase0RestrictedJsonAtomic", 1
    )[0]
    assert "SetAccessControl($attemptPath" in directory_creator
    assert "Assert-Phase0RestrictedSchedulePath -Path $attemptPath" in directory_creator


def test_scheduled_failures_and_cleanup_are_terminal_and_auditable():
    text = SCHEDULER.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    install = text.split("function Install-Phase0ScheduledTask", 1)[1].split(
        "function Test-Phase0InstalledTaskXml", 1
    )[0]
    collect = text.split("function Collect-Phase0ScheduledTask", 1)[1].split(
        "function Remove-Phase0ScheduledTask", 1
    )[0]
    cleanup = text.split("function Remove-Phase0ScheduledTask", 1)[1].split(
        "Export-ModuleMember", 1
    )[0]
    assert "SCHEDULED_TASK_START_FAILED" in install
    assert "Publish-Phase0ScheduledCollection" in install
    assert "-Final $true" in collect
    assert "SCHEDULED_TASK_TIMEOUT" in collect
    assert "[string]$PackageRoot" in cleanup
    assert "[string]$CampaignId" in cleanup
    assert "terminal-cleaned" in cleanup
    assert "Publish-Phase0ScheduledCollection" in cleanup
    remove_call = entry.rsplit("'RemoveScheduledTask'", 1)[1].split("}", 1)[0]
    assert "-PackageRoot $PackageRoot" in remove_call
    assert "-CampaignId $CampaignId" in remove_call


def test_collection_exactly_binds_installed_task_definition():
    text = SCHEDULER.read_text(encoding="utf-8")
    for required in (
        "installed_task_xml_sha256",
        "UserId",
        "StartWhenAvailable",
        "ExecNodes.Count -eq 1",
        "LogonType",
        "HighestAvailable",
        "PT6H",
        "account_sid",
    ):
        assert required in text


def test_scheduler_invokes_portable_strict_evidence_validator_and_stable_summary():
    text = SCHEDULER.read_text(encoding="utf-8")
    assert "validate-ocr-evidence" in text
    assert "runtime/python/python.exe" in text
    assert "--expected-mode" in text
    assert "--campaign-id" in text
    assert "--validation-id" in text
    assert "evidence_validation_ok" in text
    assert "validation_error_code" in text
    assert "scheduled-collection.json" in text


def test_task_definition_is_password_logon_highest_six_hours_and_dry_run_safe():
    text = SCHEDULER.read_text(encoding="utf-8")
    assert "New-Phase0TaskDefinition" in text
    assert "[switch]$DryRun" in text
    assert "-LogonType Password" in text
    assert "-RunLevel Highest" in text
    assert "New-TimeSpan -Hours 6" in text
    assert "-ExecutionTimeLimit" in text
    assert "if ($DryRun)" in text
    dry_run_body = text.split("if ($DryRun)", 1)[1].split("Register-ScheduledTask", 1)[0]
    assert "Register-ScheduledTask" not in dry_run_body


def test_scheduler_collects_bounded_redacted_evidence_and_reuses_install_attempt():
    text = SCHEDULER.read_text(encoding="utf-8")
    assert "Start-Sleep -Seconds 5" in text
    assert "New-TimeSpan -Hours 6" in text
    assert "LastTaskResult" in text
    assert "windows_session_id" in text
    assert "task_xml_sha256" in text
    assert "Get-Phase0PendingSchedule" in text
    assert "Get-Phase0AttemptContext" in text
    assert "log_summaries" in text
    assert "Get-Content -LiteralPath $LogPath" not in text
    assert "$matches = @()" not in text.lower()
    assert "SCHEDULED_OCR_FAILED" in text
    assert "SCHEDULED_OCR_PASSED" in text


def test_entrypoint_exposes_dual_run_actions_and_never_logs_secrets():
    text = ENTRY.read_text(encoding="utf-8")
    for action in (
        "RunInteractive",
        "InstallScheduledTask",
        "CollectScheduledTask",
        "RemoveScheduledTask",
    ):
        assert action in text
    lowered = text.lower()
    assert "write-output $plainpassword" not in lowered
    assert "get-childitem env:" not in lowered
    assert "convertfrom-securestring" not in lowered


def test_windows_runner_binds_campaign_mode_and_separate_output_directories():
    text = WINDOWS_RUNNER.read_text(encoding="utf-8")
    assert "[ValidateSet('Interactive', 'Scheduled')]" in text
    assert "[string]$ExecutionMode" in text
    assert "ParameterSetName='Direct')][string]$CampaignId" in text
    assert "'--campaign-id', $CampaignId" in text
    assert "'--execution-mode', $ExecutionMode.ToLowerInvariant()" in text
    assert '"work/campaigns/$CampaignId/attempts/$attemptName"' in text
    assert "Assert-Phase0RunnerArguments" in text
    assert "ValidationId and CampaignId" in SCHEDULER.read_text(encoding="utf-8")
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    assert "| Out-Host" in scheduler
    assert "return [int]$exitCode" in scheduler


def test_restricted_schedule_acl_round_trip_on_windows(tmp_path):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if os.name != "nt" or not powershell:
        pytest.skip("Windows ACL round-trip requires a Windows host")
    script = f"""
$module = Import-Module '{SCHEDULER}' -Force -PassThru
& $module {{
    param([string]$Root)
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $attemptPath = Join-Path $Root 'attempt'
    $null = New-Item -ItemType Directory -Path $attemptPath
    $attempt = [pscustomobject]@{{ root = $attemptPath; number = 1 }}
    $secure = New-Phase0RestrictedScheduleDirectory -PackageRoot $Root -Attempt $attempt `
        -ValidationId 'acl-round-trip' -AccountSid $sid
    $record = Write-Phase0RestrictedJsonAtomic -PackageRoot $Root -Directory $secure `
        -Name 'arguments.json' -Value ([ordered]@{{ ok = $true }}) -AccountSid $sid
    $null = Assert-Phase0RestrictedSchedulePath -Path $attemptPath -AccountSid $sid.Value -Kind Directory
    $null = Assert-Phase0RestrictedSchedulePath -Path $secure -AccountSid $sid.Value -Kind Directory
    $null = Assert-Phase0RestrictedSchedulePath -Path $record.path -AccountSid $sid.Value -Kind File
    $original = Get-Acl -LiteralPath $record.path
    foreach ($right in @(
        [System.Security.AccessControl.FileSystemRights]::WriteData,
        [System.Security.AccessControl.FileSystemRights]::Delete,
        [System.Security.AccessControl.FileSystemRights]::ChangePermissions
    )) {{
        $mutated = New-Phase0ScheduleSecurity -AccountSid $sid
        $bad = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid, ([System.Security.AccessControl.FileSystemRights]::ReadAndExecute -bor $right),
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $null = $mutated.SetAccessRule($bad)
        Set-Acl -LiteralPath $record.path -AclObject $mutated
        try {{
            $null = Assert-Phase0RestrictedSchedulePath -Path $record.path -AccountSid $sid.Value -Kind File
            throw "mutation right was accepted: $right"
        }} catch {{
            if ($_.Exception.Message -like 'mutation right was accepted:*') {{ throw }}
        }} finally {{
            Set-Acl -LiteralPath $record.path -AclObject $original
        }}
    }}
}} '{tmp_path}'
"""
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_task_definition_dry_run_on_windows_without_registration(tmp_path):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if os.name != "nt" or not powershell:
        pytest.skip("ScheduledTasks dry-run parsing requires a Windows host")
    validation_id = "dryrun-" + tmp_path.name.replace("_", "-")
    script = (
        f"Import-Module '{SCHEDULER}' -Force; "
        f"$d = New-Phase0TaskDefinition -ValidationId '{validation_id}' "
        "-CommandPath 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe' "
        "-RunnerPath 'C:\\phase0\\run-windows-validation.ps1' "
        "-ArgumentFile 'C:\\phase0\\scheduled-arguments.json'; "
        f"if (Get-ScheduledTask -TaskName 'UmiOcrPhase0-{validation_id}' -ErrorAction SilentlyContinue) "
        "{ throw 'dry run registered a task' }; "
        "$d | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    definition = json.loads(result.stdout.strip().splitlines()[-1])
    assert definition["task_name"] == f"UmiOcrPhase0-{validation_id}"
    assert definition["logon_type"] == "Password"
    assert definition["run_level"] == "Highest"
    assert definition["execution_time_limit"] == "PT6H"
    assert definition["argument_file"] == r"C:\phase0\scheduled-arguments.json"


def test_native_helper_keeps_stdout_out_of_exit_code_on_windows():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if os.name != "nt" or not powershell:
        pytest.skip("Native PowerShell exit behavior requires a Windows host")
    script = (
        f"Import-Module '{SCHEDULER}' -Force; "
        "$a = Invoke-Phase0NativeProcess -Executable $env:ComSpec "
        "-Arguments @('/d','/c','echo zero-visible & exit /b 0'); "
        "$b = Invoke-Phase0NativeProcess -Executable $env:ComSpec "
        "-Arguments @('/d','/c','echo seven-visible & exit /b 7'); "
        "if ($a -ne 0 -or $b -ne 7) { throw 'native exit code was polluted by stdout' }"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "zero-visible" in result.stdout
    assert "seven-visible" in result.stdout


def test_runner_relationship_guard_rejects_arbitrary_python_on_windows(tmp_path):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if os.name != "nt" or not powershell:
        pytest.skip("Windows path relationship behavior requires a Windows host")
    campaign_id = "campaign-runner-001"
    validation_id = "scheduled-runner-001"
    attempt = tmp_path / "work" / "campaigns" / campaign_id / "attempts" / "attempt-0001"
    umi = (
        tmp_path
        / "work"
        / "campaigns"
        / campaign_id
        / "umi"
        / "Umi-OCR_Rapid_v2.1.5"
        / "UmiOCR-data"
    )
    for directory in (
        attempt,
        tmp_path / "src",
        tmp_path / "runtime" / "python",
        tmp_path / "templates",
        umi / "runtime",
        umi / "plugins" / "win7_x64_RapidOCR-json",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    for path in (
        tmp_path / "runtime" / "python" / "python.exe",
        tmp_path / "templates" / "global-options.json",
        tmp_path / "templates" / "local-options.json",
        tmp_path / "templates" / "samples.json",
        umi / "runtime" / "python.exe",
    ):
        path.write_bytes(b"fixture")
    evil = tmp_path / "evil.exe"
    evil.write_bytes(b"evil")
    configuration = {
        "attempt": 1,
        "business_concurrency_limit": 5,
        "campaign_id": campaign_id,
        "execution_mode": "Scheduled",
        "global_options": str(tmp_path / "templates" / "global-options.json"),
        "local_options": str(tmp_path / "templates" / "local-options.json"),
        "min_pages": 100,
        "output_dir": str(attempt / "ocr" / "scheduled" / validation_id),
        "package_root": str(tmp_path),
        "plugin_name": "win7_x64_RapidOCR-json",
        "plugin_root": str(umi / "plugins"),
        "project_root": str(tmp_path),
        "python_exe": str(evil),
        "samples_manifest": str(tmp_path / "templates" / "samples.json"),
        "stderr_log": "",
        "stdout_log": "",
        "test_python_exe": str(tmp_path / "runtime" / "python" / "python.exe"),
        "umi_data_root": str(umi),
        "validation_id": validation_id,
    }
    serialized = json.dumps(configuration).replace("'", "''")
    script = (
        f"Import-Module '{SCHEDULER}' -Force; "
        f"$c = '{serialized}' | ConvertFrom-Json; "
        f"try {{ Assert-Phase0RunnerConfiguration -PackageRoot '{tmp_path}' -Configuration $c; "
        "throw 'arbitrary executable accepted' } catch { "
        "if ($_.Exception.Message -eq 'arbitrary executable accepted') { throw } }"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    configuration["python_exe"] = str(umi / "runtime" / "python.exe")
    output = Path(configuration["output_dir"])
    output.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside-output"
    outside.mkdir()
    linked = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(output), str(outside)],
        capture_output=True,
        check=False,
        text=True,
    )
    if linked.returncode != 0:
        pytest.skip("The Windows test account cannot create an output junction")
    serialized = json.dumps(configuration).replace("'", "''")
    script = (
        f"Import-Module '{SCHEDULER}' -Force; "
        f"$c = '{serialized}' | ConvertFrom-Json; "
        f"try {{ Assert-Phase0RunnerConfiguration -PackageRoot '{tmp_path}' -Configuration $c; "
        "throw 'output junction accepted' } catch { "
        "if ($_.Exception.Message -eq 'output junction accepted') { throw } }"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr


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


def test_case_alias_campaigns_share_windows_mutex(tmp_path):
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if os.name != "nt" or not pwsh:
        pytest.skip("Windows case-insensitive mutex behavior requires a Windows host")
    package_root = tmp_path / "case-alias[root]"
    package_root.mkdir()

    def command(campaign_id):
        return (
            f"Import-Module '{PACKAGE}' -Force; "
            f"$a = Get-Phase0AttemptContext -PackageRoot '{package_root}' "
            f"-CampaignId {campaign_id}; [Console]::Out.WriteLine($a.number)"
        )

    processes = [
        subprocess.Popen(
            [pwsh, "-NoProfile", "-NonInteractive", "-Command", command(campaign_id)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for campaign_id in ("campaign-CASE", "campaign-case")
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
