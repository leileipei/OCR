import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
ENTRY = ROOT / "scripts/phase0/Start-Phase0Validation.ps1"
PACKAGE = ROOT / "scripts/phase0/Phase0.Package.psm1"
SCHEDULER = ROOT / "scripts/phase0/Phase0.Scheduler.psm1"
WINDOWS_RUNNER = ROOT / "scripts/run-windows-validation.ps1"


def _powershell_expected_rejection(command, expected_message, message_prefix=False):
    escaped_message = expected_message.replace("'", "''")
    matches_expected = (
        "$_.Exception.Message.StartsWith("
        f"'{escaped_message}', [StringComparison]::Ordinal)"
        if message_prefix
        else f"$_.Exception.Message -ceq '{escaped_message}'"
    )
    return (
        f"try {{ {command} }} catch {{ "
        f"if ({matches_expected}) {{ exit 0 }}; "
        "[Console]::Error.WriteLine(('Unexpected rejection: ' + "
        "$_.Exception.GetType().FullName + ': ' + $_.Exception.Message)); exit 1 }; "
        "[Console]::Error.WriteLine('Expected rejection did not occur'); exit 1"
    )


def test_expected_rejection_harness_has_deterministic_exit_and_reason_contract():
    script = _powershell_expected_rejection(
        "Invoke-Guard",
        "guard rejected the untrusted input",
    )
    assert "Invoke-Guard" in script
    assert "guard rejected the untrusted input" in script
    assert "Unexpected rejection" in script
    assert "Expected rejection did not occur" in script
    assert "exit 0" in script
    assert script.endswith("exit 1")
    prefix_script = _powershell_expected_rejection(
        "Invoke-Guard",
        "guard rejected:",
        message_prefix=True,
    )
    assert ".StartsWith('guard rejected:', [StringComparison]::Ordinal)" in prefix_script


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


def test_powershell_scripts_do_not_assign_the_matches_automatic_variable():
    powershell_files = sorted(
        list((ROOT / "scripts").rglob("*.ps1"))
        + list((ROOT / "scripts").rglob("*.psm1"))
    )
    for path in powershell_files:
        normalized = (
            path.read_text(encoding="utf-8")
            .lower()
            .replace(" ", "")
            .replace("\t", "")
        )
        assert "$matches=" not in normalized, path

    entry = ENTRY.read_text(encoding="utf-8")
    assert "-ValidationId $InteractiveId -ExecutionMode interactive" in entry
    assert "-ValidationId $ScheduledId -ExecutionMode scheduled" in entry
    assert "-ValidationId $state.scheduled_validation_id -ExecutionMode scheduled" in entry


def test_entrypoint_resolves_passed_result_directories_on_windows_powershell_51(tmp_path):
    powershell = shutil.which("powershell")
    if os.name != "nt" or not powershell:
        pytest.skip("Result-directory parsing requires Windows PowerShell 5.1")

    package_root = tmp_path / "entry-results"
    attempts = package_root / "work/campaigns/campaign-results/attempts"
    interactive = attempts / "attempt-0001/ocr/interactive/interactive-results"
    scheduled = attempts / "attempt-0002/run/scheduled/output/scheduled-results"
    interactive.mkdir(parents=True)
    scheduled.mkdir(parents=True)
    collection_attempt = attempts / "attempt-0003"
    collection_attempt.mkdir()
    (attempts / "attempt-0001/interactive-validation-summary.json").write_text(
        json.dumps(
            {
                "campaign_id": "campaign-results",
                "validation_id": "interactive-results",
                "result": "passed",
                "collection_attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    (collection_attempt / "scheduled-collection.json").write_text(
        json.dumps(
            {
                "campaign_id": "campaign-results",
                "validation_id": "scheduled-results",
                "result": "passed",
                "final": True,
                "collection_attempt": 3,
                "install_attempt": 2,
            }
        ),
        encoding="utf-8",
    )

    escaped_entry = str(ENTRY).replace("'", "''")
    escaped_package = str(PACKAGE).replace("'", "''")
    escaped_root = str(package_root).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {{
    throw 'Windows PowerShell 5.1 is required'
}}
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{escaped_entry}', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) {{ throw 'Entry script parse failed' }}
Import-Module '{escaped_package}' -Force
function Test-Phase0CampaignSecurityPath {{ param([string]$Path) return $Path }}
$required = @('Assert-Phase0EntryIdentifier', 'Assert-Phase0EntryControlledPath', 'Get-Phase0EntryResultsDirectory')
$definitions = $ast.FindAll({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $required -contains $node.Name
}}, $true)
if ($definitions.Count -ne $required.Count) {{ throw 'Required entry helpers were not found' }}
Invoke-Expression (($definitions | ForEach-Object {{ $_.Extent.Text }}) -join [Environment]::NewLine)
$interactive = Get-Phase0EntryResultsDirectory -PackageRoot '{escaped_root}' `
    -CampaignId 'campaign-results' -ValidationId 'interactive-results' -ExecutionMode interactive
$scheduled = Get-Phase0EntryResultsDirectory -PackageRoot '{escaped_root}' `
    -CampaignId 'campaign-results' -ValidationId 'scheduled-results' -ExecutionMode scheduled
[pscustomobject]@{{ interactive = $interactive; scheduled = $scheduled }} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout.strip())
    assert Path(value["interactive"]) == interactive
    assert Path(value["scheduled"]) == scheduled


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


def test_runner_allows_only_the_trusted_repository_project_root_special_case():
    text = SCHEDULER.read_text(encoding="utf-8")
    assert "$name -eq 'project_root'" in text
    assert "$projectPath.Equals($root, [System.StringComparison]::OrdinalIgnoreCase)" in text
    assert "Get-Item -LiteralPath $root -Force" in text
    assert "Trusted project root is not a regular directory" in text
    assert "Trusted project root is a reparse point" in text
    for name in (
        "umi_data_root",
        "test_python_exe",
        "python_exe",
        "plugin_root",
        "global_options",
        "local_options",
        "samples_manifest",
    ):
        assert name in text


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
        "function Assert-Phase0WritableScheduleDirectory", 1
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


def test_scheduled_acl_domains_separate_secure_inputs_from_exact_writable_runtime():
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    runner = WINDOWS_RUNNER.read_text(encoding="utf-8")
    assert "New-Phase0ScheduleRuntimeDirectories" in scheduler
    assert "Assert-Phase0WritableScheduleDirectory" in scheduler
    for relative in (
        "run/scheduled/logs",
        "run/scheduled/output",
        "run/scheduled/temp",
    ):
        assert relative in scheduler
    assert '"run/scheduled/output/$validation"' in scheduler
    assert '"run/scheduled/logs/stdout.log"' in scheduler
    assert '"run/scheduled/logs/stderr.log"' in scheduler
    assert '"run/scheduled/temp"' in scheduler
    assert "Assert-Phase0ScheduleRuntimeDirectories" in scheduler
    assert "[string]$Configuration.temp_dir" in scheduler
    assert "$env:TEMP = $TempDir" in runner
    assert "$env:TMP = $TempDir" in runner
    assert "$env:TMPDIR = $TempDir" in runner
    assert "$scheduled = $ExecutionMode -eq 'Scheduled'" in scheduler


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


def test_scheduled_collection_revalidates_evidence_tree_before_validator():
    text = SCHEDULER.read_text(encoding="utf-8")
    collect = text.split("function Collect-Phase0ScheduledTask", 1)[1].split(
        "function Remove-Phase0ScheduledTask", 1
    )[0]
    guard = (
        "Test-Phase0EvidenceTree -PackageRoot $PackageRoot "
        "-Path $configuration.output_dir"
    )
    validator = "Invoke-Phase0EvidenceValidator -PackageRoot $PackageRoot"
    assert guard in collect
    assert validator in collect
    assert collect.index(guard) < collect.index(validator)


def test_post_registration_failures_share_compensation_boundary_and_orphan_cleanup():
    text = SCHEDULER.read_text(encoding="utf-8")
    install = text.split("function Install-Phase0ScheduledTask", 1)[1].split(
        "function Test-Phase0InstalledTaskXml", 1
    )[0]
    cleanup = text.split("function Remove-Phase0ScheduledTask", 1)[1].split(
        "Export-ModuleMember", 1
    )[0]
    assert "$registered = $false" in install
    assert "$metadataDurable = $false" in install
    assert "$registered = $true" in install
    assert "$metadataDurable = $true" in install
    assert "Invoke-Phase0RegistrationCompensation" in install
    for operation in (
        "Export-ScheduledTask",
        "Test-Phase0InstalledTaskXml",
        "Write-Phase0RestrictedJsonAtomic -PackageRoot $root -Directory $secureDirectory -Name 'install-metadata.json'",
    ):
        assert install.index("$registered = $true") < install.index(operation)
        assert install.index(operation) < install.index("$metadataDurable = $true")
    assert "scheduled-install-compensation.json" in text
    assert "install_error_type" in text
    assert "cleanup_error_type" in text
    assert "Stop-ScheduledTask" in text
    assert "Unregister-ScheduledTask" in text
    assert "scheduled-cleanup-intent.json" in cleanup
    assert "scheduled-cleanup-outcome.json" in cleanup
    assert "Get-ScheduledTask -TaskName $TaskName" in cleanup


def test_cleanup_requires_owned_record_and_audits_before_external_changes():
    text = SCHEDULER.read_text(encoding="utf-8")
    cleanup = text.split("function Remove-Phase0ScheduledTask", 1)[1].split(
        "Export-ModuleMember", 1
    )[0]
    assert "Get-Phase0InstallCompensationRecords" in text
    assert "Test-Phase0CompensatedTaskXml" in text
    assert "orphaned_task -ne $true" in text
    assert "Expected exactly one trusted orphan compensation record" in text
    assert "scheduled-cleanup-intent.json" in cleanup
    assert "scheduled-cleanup-outcome.json" in cleanup
    assert "source_record_relative" in cleanup
    assert "task_xml_sha256" in cleanup
    assert cleanup.index("scheduled-cleanup-intent.json") < cleanup.index("Stop-ScheduledTask")
    assert cleanup.index("Stop-ScheduledTask") < cleanup.index("scheduled-cleanup-outcome.json")
    assert "stop_error_type" in cleanup
    assert "unregister_error_type" in cleanup
    assert "Export-ScheduledTask" in cleanup


def test_install_exposes_scoped_fault_hooks_inside_real_registration_boundary():
    text = SCHEDULER.read_text(encoding="utf-8")
    install = text.split("function Install-Phase0ScheduledTask", 1)[1].split(
        "function Test-Phase0InstalledTaskXml", 1
    )[0]
    assert "[ValidateSet('', 'Export', 'Xml', 'Metadata')]" in install
    assert "$FaultInjection -eq 'Export'" in install
    assert "$FaultInjection -eq 'Xml'" in install
    assert "$FaultInjection -eq 'Metadata'" in install
    assert install.index("$registered = $true") < install.index("$FaultInjection -eq 'Export'")
    assert install.index("$FaultInjection -eq 'Metadata'") < install.index("$metadataDurable = $true")


def test_scheduled_credentials_and_runner_reject_effective_administrator_tokens():
    text = SCHEDULER.read_text(encoding="utf-8")
    install = text.split("function Install-Phase0ScheduledTask", 1)[1].split(
        "function Test-Phase0InstalledTaskXml", 1
    )[0]
    assert "Assert-Phase0ScheduledCredentialNonAdministrator" in text
    assert "Assert-Phase0CurrentScheduledIdentityNonAdministrator" in text
    assert "WindowsPrincipal" in text
    assert "BuiltinAdministratorsSid" in text
    assert "LogonUser" in text
    assert "S-1-5-32-544" in text
    assert install.index("Assert-Phase0ScheduledCredentialNonAdministrator") < install.index(
        "Get-Phase0AttemptContext"
    )


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


def test_campaign_evidence_directories_use_protected_fail_closed_acl_contract():
    package = PACKAGE.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    creator = package.split("function New-Phase0ProtectedDirectory", 1)[1].split(
        "function Test-Phase0EvidenceTree", 1
    )[0]
    assert "function New-Phase0CampaignSecurity" in package
    assert "SetAccessRuleProtection($true, $false)" in package
    assert "function Test-Phase0CampaignSecurityPath" in package
    assert "Campaign ACL inheritance must be disabled" in package
    assert "Campaign owner is not trusted" in package
    assert "New-Phase0ProtectedDirectory" in package
    assert "Test-Phase0CampaignSecurityPath" in entry
    assert "Test-Phase0CampaignSecurityPath -Path $attemptsRoot" in entry
    assert "$PSVersionTable.PSEdition -eq 'Desktop'" in creator
    assert "$PSVersionTable.PSEdition -eq 'Core'" in creator
    assert "(New-Object System.IO.DirectoryInfo($target)).Create($security)" in creator
    assert "DirectoryInfo.Create(DirectorySecurity) is unavailable" in creator
    assert "[System.IO.FileSystemAclExtensions]::Create($directoryInfo, $security)" in creator
    assert "FileSystemAclExtensions.Create is unavailable" in creator
    assert "Unsupported PowerShell edition for protected ACL creation" in creator
    assert "[System.IO.Directory]::CreateDirectory($target, $security)" not in creator
    assert "Set-Acl" not in creator


def test_package_exports_only_approved_verbs_without_hiding_import_warnings():
    package = PACKAGE.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    exports = package.split("Export-ModuleMember -Function @(", 1)[1]
    names = re.findall(r"'([A-Za-z]+-Phase0[A-Za-z]+)'", exports)
    approved_verbs = {"Test", "Invoke", "Get", "Set", "Write", "Enter", "Exit", "New"}
    assert names
    assert all(name.split("-", 1)[0] in approved_verbs for name in names)
    for old_name in (
        "Assert-Phase0CampaignSecurityPath",
        "Ensure-Phase0ProtectedDirectory",
        "Assert-Phase0EvidenceTree",
    ):
        assert old_name not in exports
    for new_name in (
        "Test-Phase0CampaignSecurityPath",
        "New-Phase0ProtectedDirectory",
        "Test-Phase0EvidenceTree",
    ):
        assert new_name in exports
    assert "DisableNameChecking" not in package + entry + scheduler


@pytest.mark.parametrize("engine_name", ["powershell", "pwsh"])
def test_campaign_acl_denies_unprivileged_read_and_allows_administrator_on_windows(
    tmp_path, engine_name
):
    if os.name != "nt":
        pytest.skip("Windows campaign ACL behavior requires a Windows host")
    powershell = shutil.which(engine_name)
    if not powershell:
        pytest.skip(f"{engine_name} is not installed")
    script = rf"""
$userName = 'UmiEvidence' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$root = Join-Path $env:ProgramData ('UmiOcrEvidenceAcl-' + [guid]::NewGuid().ToString('N'))
$createdUser = $false
if (-not (Get-Command New-LocalUser -ErrorAction SilentlyContinue)) {{ exit 77 }}
try {{
    $null = New-Item -ItemType Directory -Path $root
    $password = ConvertTo-SecureString ('Umi!' + [guid]::NewGuid().ToString('N') + '9a') -AsPlainText -Force
    $user = New-LocalUser -Name $userName -Password $password -PasswordNeverExpires -UserMayNotChangePassword
    $createdUser = $true
    $credential = New-Object System.Management.Automation.PSCredential("$env:COMPUTERNAME\$userName", $password)
    $module = Import-Module '{PACKAGE}' -Force -PassThru
    $attempt = Get-Phase0AttemptContext -PackageRoot $root -CampaignId 'campaign-acl-proof'
    $evidence = Join-Path $attempt.root 'full-ocr-text.json'
    [System.IO.File]::WriteAllText($evidence, '{{"ocr_text":"sensitive"}}')
    $null = & $module {{ param($Path) Test-Phase0CampaignSecurityPath -Path $Path }} $attempt.root
    if ([System.IO.File]::ReadAllText($evidence) -notmatch 'sensitive') {{ throw 'administrator could not read evidence' }}
    $child = @"
try {{ [System.IO.File]::ReadAllText('$evidence') | Out-Null; exit 12 }}
catch [System.UnauthorizedAccessException] {{ exit 0 }}
"@
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($child))
    $hostExecutable = (Get-Process -Id $PID).Path
    $process = Start-Process -FilePath $hostExecutable -Credential $credential `
        -ArgumentList "-NoProfile -NonInteractive -EncodedCommand $encoded" `
        -WorkingDirectory $env:SystemRoot -Wait -PassThru
    if ($process.ExitCode -ne 0) {{ throw "unprivileged ACL probe failed: $($process.ExitCode)" }}
}}
catch {{
    if (-not $createdUser) {{ exit 77 }}
    throw
}}
finally {{
    if ($createdUser) {{ Remove-LocalUser -Name $userName -ErrorAction SilentlyContinue }}
    if (Test-Path -LiteralPath $root) {{ Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue }}
}}
"""
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 77:
        pytest.skip("Windows host cannot provision a temporary non-admin local account")
    assert result.returncode == 0, result.stderr


def test_collection_entry_requires_plain_evidence_tree_contract():
    package = PACKAGE.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    assert "function Test-Phase0EvidenceTree" in package
    assert "Evidence tree contains a reparse point:" in package
    assert "Test-Phase0EvidenceTree -PackageRoot $PackageRoot -Path $candidate" in entry


def test_collection_rejects_windows_junction_in_evidence_tree(tmp_path):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if os.name != "nt" or not powershell:
        pytest.skip("Windows evidence junction behavior requires a Windows host")
    package_root = tmp_path / "package"
    results = package_root / "work/campaigns/campaign-junction/results"
    outside = tmp_path / "outside"
    results.mkdir(parents=True)
    outside.mkdir()
    linked = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(results / "redirected"), str(outside)],
        capture_output=True,
        check=False,
        text=True,
    )
    if linked.returncode != 0:
        pytest.skip("The Windows test account cannot create an evidence junction")
    script = (
        f"Import-Module '{PACKAGE}' -Force; "
        + _powershell_expected_rejection(
            f"Test-Phase0EvidenceTree -PackageRoot '{package_root}' -Path '{results}'",
            "Evidence tree contains a reparse point:",
            message_prefix=True,
        )
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_restricted_schedule_acl_round_trip_with_non_admin_account_on_windows():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if os.name != "nt" or not powershell:
        pytest.skip("Windows ACL round-trip requires a Windows host")
    script = rf"""
$userName = 'UmiAcl' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$root = Join-Path $env:ProgramData ('UmiOcrAclTest-' + [guid]::NewGuid().ToString('N'))
$createdUser = $false
if (-not (Get-Command New-LocalUser -ErrorAction SilentlyContinue)) {{ exit 77 }}
try {{
    $null = New-Item -ItemType Directory -Path $root
    $password = ConvertTo-SecureString ('Umi!' + [guid]::NewGuid().ToString('N') + '9a') -AsPlainText -Force
    $user = New-LocalUser -Name $userName -Password $password -PasswordNeverExpires -UserMayNotChangePassword
    $createdUser = $true
    $sid = $user.SID
    $credential = New-Object System.Management.Automation.PSCredential("$env:COMPUTERNAME\$userName", $password)
$module = Import-Module '{SCHEDULER}' -Force -PassThru
    try {{
        $null = & $module {{
            $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
            Assert-Phase0CurrentScheduledIdentityNonAdministrator -ExpectedSid $currentSid
        }}
        throw 'administrator runner token was accepted'
    }} catch {{
        if ($_.Exception.Message -cne 'Scheduled runner must not execute with an Administrators token') {{ throw }}
    }}
    $paths = & $module {{
        param([string]$Root, $Sid)
        $attemptPath = Join-Path $Root 'attempt'
        $null = New-Item -ItemType Directory -Path $attemptPath
        $attempt = [pscustomobject]@{{ root = $attemptPath; number = 1 }}
        $secure = New-Phase0RestrictedScheduleDirectory -PackageRoot $Root -Attempt $attempt `
            -ValidationId 'acl-round-trip' -AccountSid $Sid
        $runtime = New-Phase0ScheduleRuntimeDirectories -PackageRoot $Root -Attempt $attempt -AccountSid $Sid
        $arguments = Write-Phase0RestrictedJsonAtomic -PackageRoot $Root -Directory $secure `
            -Name 'arguments.json' -Value ([ordered]@{{ ok = $true }}) -AccountSid $Sid
        $metadata = Write-Phase0RestrictedJsonAtomic -PackageRoot $Root -Directory $secure `
            -Name 'install-metadata.json' -Value ([ordered]@{{ ok = $true }}) -AccountSid $Sid
        [pscustomobject]@{{
            arguments = $arguments.path; metadata = $metadata.path; secure = $secure
            logs = $runtime.logs; output = $runtime.output; temp = $runtime.temp
            attempt = $attemptPath; run = Join-Path $attemptPath 'run'
            scheduled = Join-Path $attemptPath 'run\scheduled'
        }}
    }} $root $sid
    $null = & $module {{ param($Credential, $Sid) Assert-Phase0ScheduledCredentialNonAdministrator -Credential $Credential -ExpectedSid $Sid }} $credential $sid
    $argumentsHash = (Get-FileHash -LiteralPath $paths.arguments -Algorithm SHA256).Hash
    $metadataHash = (Get-FileHash -LiteralPath $paths.metadata -Algorithm SHA256).Hash
    $child = @"
`$ErrorActionPreference = 'Stop'
`$log = New-Object System.IO.FileStream('$($paths.logs)\probe.log', [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
`$log.WriteByte(1); `$log.Dispose()
`$null = [System.IO.Directory]::CreateDirectory('$($paths.output)\probe-output')
[System.IO.File]::WriteAllText('$($paths.temp)\probe.tmp', 'ok')
`$protectedFiles = [ordered]@{{
    '$($paths.arguments)' = '$argumentsHash'
    '$($paths.metadata)' = '$metadataHash'
}}
`$requiredPaths = @(
    '$($paths.secure)', '$($paths.attempt)', '$($paths.run)', '$($paths.scheduled)',
    '$($paths.logs)', '$($paths.output)', '$($paths.temp)'
)
`$moveSources = @(`$protectedFiles.Keys) + @(
    '$($paths.secure)', '$($paths.attempt)', '$($paths.run)', '$($paths.scheduled)',
    '$($paths.logs)', '$($paths.output)', '$($paths.temp)'
)
function Assert-ProbeState {{
    foreach (`$entry in `$protectedFiles.GetEnumerator()) {{
        `$path = [string]`$entry.Key
        if (-not (Test-Path -LiteralPath `$path -PathType Leaf)) {{
            throw "protected file was removed: `$path"
        }}
        if ((Get-FileHash -LiteralPath `$path -Algorithm SHA256).Hash -ne [string]`$entry.Value) {{
            throw "protected file was changed: `$path"
        }}
    }}
    foreach (`$path in `$requiredPaths) {{
        if (-not (Test-Path -LiteralPath `$path)) {{
            throw "partial deletion or move changed the ACL probe tree: `$path"
        }}
    }}
    foreach (`$path in `$moveSources) {{
        if (Test-Path -LiteralPath (`$path + '.moved')) {{
            throw "partial deletion or move changed the ACL probe tree: `$path"
        }}
    }}
}}
function Invoke-ExpectedDeniedMutation {{
    param([scriptblock]`$Operation)
    try {{ & `$Operation }} catch {{ }}
    Assert-ProbeState
}}
Assert-ProbeState
foreach (`$target in @('$($paths.arguments)', '$($paths.metadata)')) {{
    Invoke-ExpectedDeniedMutation {{ [System.IO.File]::WriteAllText(`$target, 'tampered') }}
    Invoke-ExpectedDeniedMutation {{ [System.IO.File]::Delete(`$target) }}
    Invoke-ExpectedDeniedMutation {{ [System.IO.File]::Move(`$target, (`$target + '.moved')) }}
}}
Invoke-ExpectedDeniedMutation {{ [System.IO.Directory]::Delete('$($paths.secure)', `$true) }}
foreach (`$rootPath in @(
    '$($paths.attempt)', '$($paths.run)', '$($paths.scheduled)',
    '$($paths.logs)', '$($paths.output)', '$($paths.temp)'
)) {{
    Invoke-ExpectedDeniedMutation {{ [System.IO.Directory]::Delete(`$rootPath, `$true) }}
    Invoke-ExpectedDeniedMutation {{ [System.IO.Directory]::Move(`$rootPath, (`$rootPath + '.moved')) }}
}}
exit 0
"@
    $probeScript = Join-Path $root 'acl-probe.ps1'
    [System.IO.File]::WriteAllText($probeScript, $child, (New-Object System.Text.UTF8Encoding($false)))
    $hostExecutable = (Get-Process -Id $PID).Path
    $process = Start-Process -FilePath $hostExecutable -Credential $credential `
        -ArgumentList "-NoProfile -NonInteractive -File `"$probeScript`"" `
        -WorkingDirectory $env:SystemRoot -Wait -PassThru
    if ($process.ExitCode -ne 0) {{ throw "non-admin ACL probe failed: $($process.ExitCode)" }}
    if ((Get-FileHash -LiteralPath $paths.arguments -Algorithm SHA256).Hash -ne $argumentsHash -or
        (Get-FileHash -LiteralPath $paths.metadata -Algorithm SHA256).Hash -ne $metadataHash) {{
        throw 'secure schedule evidence changed during low-privilege probe'
    }}
    $administratorGroup = (New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')).Translate(
        [System.Security.Principal.NTAccount]
    ).Value.Split('\')[-1]
    Add-LocalGroupMember -Group $administratorGroup -Member $userName
    try {{
        $null = & $module {{ param($Credential, $Sid) Assert-Phase0ScheduledCredentialNonAdministrator -Credential $Credential -ExpectedSid $Sid }} $credential $sid
        throw 'administrator credential was accepted'
    }} catch {{
        if ($_.Exception.Message -cne 'Scheduled execution account must not belong to BUILTIN\Administrators') {{ throw }}
    }}
}}
catch {{
    if (-not $createdUser) {{ exit 77 }}
    throw
}}
finally {{
    if ($createdUser) {{ Remove-LocalUser -Name $userName -ErrorAction SilentlyContinue }}
    if (Test-Path -LiteralPath $root) {{ Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue }}
}}
"""
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 77:
        pytest.skip("Windows host cannot provision a temporary non-admin local account")
    assert result.returncode == 0, result.stderr


def test_registration_compensation_removes_fault_injected_tasks_on_windows():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if os.name != "nt" or not powershell:
        pytest.skip("Task Scheduler compensation requires a Windows host")
    script = rf"""
if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {{ exit 77 }}
$userName = 'UmiComp' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$root = Join-Path $env:ProgramData ('UmiOcrCompensationTest-' + [guid]::NewGuid().ToString('N'))
$createdUser = $false
$createdTasks = @()
try {{
    if (-not (Get-Command New-LocalUser -ErrorAction SilentlyContinue)) {{ exit 77 }}
    $null = New-Item -ItemType Directory -Path $root
    $runner = Join-Path $root 'run-windows-validation.ps1'
    [System.IO.File]::WriteAllText($runner, "exit 0`n", (New-Object System.Text.UTF8Encoding($false)))
    $password = ConvertTo-SecureString ('Umi!' + [guid]::NewGuid().ToString('N') + '9a') -AsPlainText -Force
    $user = New-LocalUser -Name $userName -Password $password -PasswordNeverExpires -UserMayNotChangePassword
    $createdUser = $true
    $credential = New-Object System.Management.Automation.PSCredential("$env:COMPUTERNAME\$userName", $password)
    $module = Import-Module '{SCHEDULER}' -Force -PassThru
    & $module {{
        param([string]$Runner)
        $script:CompensationTestRunner = $Runner
        function script:Get-Phase0State {{
            [pscustomobject]@{{ state = 'INTERACTIVE_OCR_PASSED'; interactive_validation_id = 'interactive-source' }}
        }}
        function script:Get-Phase0ScheduleRecords {{ @() }}
        function script:Get-Phase0AttemptContext {{
            param([string]$PackageRoot, [string]$CampaignId)
            $attemptRoot = Join-Path $PackageRoot ("work\campaigns\$CampaignId\attempts\attempt-" + ('{{0:D4}}' -f $script:CompensationTestAttempt))
            $null = New-Item -ItemType Directory -Path $attemptRoot -Force
            [pscustomobject]@{{ root = $attemptRoot; number = $script:CompensationTestAttempt }}
        }}
        function script:Get-Phase0RunnerConfiguration {{
            [ordered]@{{ schema_version = '1.0'; execution_mode = 'Scheduled'; test_only = $true }}
        }}
        function script:Assert-Phase0RunnerConfiguration {{ param($PackageRoot, $Configuration) $Configuration }}
        function script:Get-Phase0RunnerScript {{ param($PackageRoot) $script:CompensationTestRunner }}
        function script:Test-Phase0InstalledTaskXml {{ $true }}
    }} $runner
    foreach ($definition in @(
        [pscustomobject]@{{ number = 1; stage = 'Export' }},
        [pscustomobject]@{{ number = 2; stage = 'Xml' }},
        [pscustomobject]@{{ number = 3; stage = 'Metadata' }}
    )) {{
        $campaign = 'campaign-compensation'
        $validation = 'fault-' + $definition.number
        $taskName = 'UmiOcrPhase0-' + $validation
        $createdTasks += $taskName
        & $module {{ param([int]$Number) $script:CompensationTestAttempt = $Number }} $definition.number
        $expectedFault = switch ($definition.stage) {{
            'Export' {{ 'Injected export failure' }}
            'Xml' {{ 'Injected XML validation failure' }}
            'Metadata' {{ 'Injected metadata publish failure' }}
        }}
        try {{
            Install-Phase0ScheduledTask -PackageRoot $root -CampaignId $campaign -ValidationId $validation `
                -Credential $credential -FaultInjection $definition.stage
            throw 'fault injection unexpectedly completed'
        }} catch {{
            if ($_.Exception.Message -cne $expectedFault) {{ throw }}
        }}
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {{ throw 'fault left an orphan task' }}
        $attemptRoot = Join-Path $root ("work\campaigns\$campaign\attempts\attempt-" + ('{{0:D4}}' -f $definition.number))
        $path = Join-Path $attemptRoot ("secure\schedule-$validation\scheduled-install-compensation.json")
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {{ throw 'compensation record is missing' }}
        $record = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        if (-not $record.unregister_succeeded -or $record.orphaned_task -or
            $record.validation_id -ne $validation -or $record.install_attempt -ne $definition.number) {{
            throw 'compensation record did not bind the injected stage'
        }}
    }}
}}
catch {{
    if (-not $createdUser) {{ exit 77 }}
    throw
}}
finally {{
    foreach ($taskName in $createdTasks) {{
        Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue
    }}
    if ($createdUser) {{ Remove-LocalUser -Name $userName -ErrorAction SilentlyContinue }}
    if (Test-Path -LiteralPath $root) {{ Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue }}
}}
"""
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 77:
        pytest.skip("Windows host cannot provision the scheduled-task test account")
    assert result.returncode == 0, result.stderr


def test_credentialed_windows_probes_use_safe_system_working_directory():
    source = Path(__file__).read_text(encoding="utf-8")
    campaign_probe = source.split(
        "\ndef test_campaign_acl_denies_unprivileged_read_and_allows_administrator_on_windows",
        1,
    )[1].split("\ndef test_collection_entry_requires_plain_evidence_tree_contract", 1)[0]
    schedule_probe = source.split(
        "\ndef test_restricted_schedule_acl_round_trip_with_non_admin_account_on_windows",
        1,
    )[1].split(
        "\ndef test_registration_compensation_removes_fault_injected_tasks_on_windows", 1
    )[0]
    for probe in (campaign_probe, schedule_probe):
        assert 'PSCredential("$env:COMPUTERNAME\\$userName", $password)' in probe
        assert "Start-Process -FilePath $hostExecutable -Credential $credential" in probe
        assert "-WorkingDirectory $env:SystemRoot" in probe
    assert "$probeScript = Join-Path $root 'acl-probe.ps1'" in schedule_probe
    assert '-ArgumentList "-NoProfile -NonInteractive -File `"$probeScript`""' in schedule_probe
    assert "-EncodedCommand $encoded" not in schedule_probe
    assert "function Test-AccessDeniedError" not in schedule_probe
    assert "function Assert-ProbeState" in schedule_probe
    assert "function Invoke-ExpectedDeniedMutation" in schedule_probe
    assert schedule_probe.count("Invoke-ExpectedDeniedMutation") == 7
    assert "Test-Path -LiteralPath `$path" in schedule_probe
    assert "Get-FileHash -LiteralPath `$path" in schedule_probe
    assert "partial deletion or move changed the ACL probe tree" in schedule_probe
    required_paths = schedule_probe.split("`$requiredPaths = @(", 1)[1].split("\n)", 1)[0]
    assert "'$($paths.logs)\\probe.log'" not in required_paths
    assert "'$($paths.output)\\probe-output'" not in required_paths
    assert "'$($paths.temp)\\probe.tmp'" not in required_paths
    assert "$probePaths = @(" not in schedule_probe
    assert "runtime probe was removed" not in schedule_probe
    assert "`$ErrorActionPreference = 'Stop'" in schedule_probe
    assert "[System.IO.FileMode]::CreateNew" in schedule_probe
    assert "[System.IO.Directory]::CreateDirectory('$($paths.output)\\probe-output')" in schedule_probe
    assert "[System.IO.File]::WriteAllText('$($paths.temp)\\probe.tmp', 'ok')" in schedule_probe
    assert "catch [System.UnauthorizedAccessException]" not in schedule_probe


def test_local_scheduled_account_alias_is_canonicalized_before_sid_translation():
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    assert "function ConvertTo-Phase0ScheduledAccountName" in scheduler
    assert "$Credential.UserName.StartsWith('.\\')" in scheduler
    assert 'return "$env:COMPUTERNAME\\$localName"' in scheduler
    install = scheduler.split("function Install-Phase0ScheduledTask", 1)[1]
    assert (
        "$userName = ConvertTo-Phase0ScheduledAccountName -Credential $Credential"
        in install
    )
    assert "NTAccount($Credential.UserName)" not in install


def test_compensation_fault_overrides_persist_in_scheduler_module_script_scope():
    source = Path(__file__).read_text(encoding="utf-8")
    compensation = source.split(
        "\ndef test_registration_compensation_removes_fault_injected_tasks_on_windows", 1
    )[1].split(
        "\ndef test_credentialed_windows_probes_use_safe_system_working_directory", 1
    )[0]
    for function_name in (
        "Get-Phase0State",
        "Get-Phase0ScheduleRecords",
        "Get-Phase0AttemptContext",
        "Get-Phase0RunnerConfiguration",
        "Assert-Phase0RunnerConfiguration",
        "Get-Phase0RunnerScript",
        "Test-Phase0InstalledTaskXml",
    ):
        assert "function script:" + function_name + " {{" in compensation
        assert "function " + function_name + " {{" not in compensation


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
        "output_dir": str(attempt / "run" / "scheduled" / "output" / validation_id),
        "package_root": str(tmp_path),
        "plugin_name": "win7_x64_RapidOCR-json",
        "plugin_root": str(umi / "plugins"),
        "project_root": str(tmp_path),
        "python_exe": str(evil),
        "samples_manifest": str(tmp_path / "templates" / "samples.json"),
        "stderr_log": str(attempt / "run" / "scheduled" / "logs" / "stderr.log"),
        "stdout_log": str(attempt / "run" / "scheduled" / "logs" / "stdout.log"),
        "temp_dir": str(attempt / "run" / "scheduled" / "temp"),
        "test_python_exe": str(tmp_path / "runtime" / "python" / "python.exe"),
        "umi_data_root": str(umi),
        "validation_id": validation_id,
    }
    serialized = json.dumps(configuration).replace("'", "''")
    script = f"Import-Module '{SCHEDULER}' -Force; $c = '{serialized}' | ConvertFrom-Json; " + (
        _powershell_expected_rejection(
            f"Assert-Phase0RunnerConfiguration -PackageRoot '{tmp_path}' -Configuration $c",
            "python_exe is outside the trusted package relationship",
        )
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    configuration["python_exe"] = str(umi / "runtime" / "python.exe")
    serialized = json.dumps(configuration).replace("'", "''")
    script = (
        f"Import-Module '{SCHEDULER}' -Force; "
        f"$c = '{serialized}' | ConvertFrom-Json; "
        f"$null = Assert-Phase0RunnerConfiguration -PackageRoot '{tmp_path}' -Configuration $c; "
        "exit 0"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr

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
    script = f"Import-Module '{SCHEDULER}' -Force; $c = '{serialized}' | ConvertFrom-Json; " + (
        _powershell_expected_rejection(
            f"Assert-Phase0RunnerConfiguration -PackageRoot '{tmp_path}' -Configuration $c",
            "Runtime path contains a reparse point:",
            message_prefix=True,
        )
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
