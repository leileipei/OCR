param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        'Preflight', 'Prepare', 'SelfTest', 'RunInteractive',
        'InstallScheduledTask', 'CollectScheduledTask', 'ExportEvidence',
        'ResumeE10', 'BuildFinalReport', 'RemoveScheduledTask'
    )]
    [string]$Action,
    [string]$PackageRoot = '',
    [string]$CampaignId = ('campaign-' + [guid]::NewGuid().ToString('N')),
    [string]$ValidationId = ([guid]::NewGuid().ToString('N')),
    [string]$InteractiveId = '',
    [string]$ScheduledId = '',
    [string]$E10EvidencePath = '',
    [string]$ScheduledResultsDir = '',
    [string]$FinalReportPath = '',
    [System.Management.Automation.PSCredential]$Credential,
    [switch]$ConfirmCleanup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$moduleImported = $false
$rootResolved = $false
$campaignLock = $null
$attempt = $null
$exitCode = 1

function Assert-Phase0EntryIdentifier {
    param([string]$Value, [string]$Name)
    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
        throw "$Name must contain only safe identifier characters and be at most 128 characters"
    }
}

function Assert-Phase0EntryControlledPath {
    param(
        [string]$ControlledRoot,
        [string]$Path,
        [ValidateSet('File', 'Directory', 'MissingOrFile')][string]$Expected
    )
    if ([string]::IsNullOrWhiteSpace($Path) -or $Path -match '[\x00-\x1F\x7F]') {
        throw 'A required controlled path is missing or unsafe'
    }
    $rootItem = Get-Item -LiteralPath $ControlledRoot -Force
    if (-not $rootItem.PSIsContainer -or
        ($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Controlled root must be a normal directory: $ControlledRoot"
    }
    $root = [System.IO.Path]::GetFullPath($rootItem.FullName).TrimEnd('\', '/')
    $candidate = [System.IO.Path]::GetFullPath($Path)
    $rootPrefix = $root + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside the controlled campaign directory: $Path"
    }
    $current = if (Test-Path -LiteralPath $candidate) { $candidate } else { [System.IO.Path]::GetDirectoryName($candidate) }
    while (-not [string]::IsNullOrWhiteSpace($current) -and
        -not $current.Equals($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Controlled path contains a reparse point: $current"
            }
        }
        $current = [System.IO.Path]::GetDirectoryName($current.TrimEnd('\', '/'))
    }
    if ($Expected -eq 'File' -and -not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Controlled file is missing: $candidate"
    }
    if ($Expected -eq 'Directory' -and -not (Test-Path -LiteralPath $candidate -PathType Container)) {
        throw "Controlled directory is missing: $candidate"
    }
    if ($Expected -eq 'MissingOrFile' -and (Test-Path -LiteralPath $candidate -PathType Container)) {
        throw "Controlled output path is a directory: $candidate"
    }
    return $candidate
}

function Get-Phase0EntryProjectRoot {
    param([string]$PackageRoot)
    if (Test-Path -LiteralPath (Join-Path $PackageRoot 'toolkit/src') -PathType Container) {
        return Join-Path $PackageRoot 'toolkit'
    }
    return $PackageRoot
}

function Get-Phase0EntryResultsDirectory {
    param(
        [string]$PackageRoot,
        [string]$CampaignId,
        [string]$ValidationId,
        [ValidateSet('interactive', 'scheduled')][string]$ExecutionMode
    )
    Assert-Phase0EntryIdentifier -Value $ValidationId -Name 'ValidationId'
    $attemptsRoot = Join-Path $PackageRoot "work/campaigns/$CampaignId/attempts"
    $null = Assert-Phase0EntryControlledPath -ControlledRoot $PackageRoot -Path $attemptsRoot -Expected Directory
    $null = Test-Phase0CampaignSecurityPath -Path $attemptsRoot
    $resultDirectories = @()
    foreach ($directory in Get-ChildItem -LiteralPath $attemptsRoot -Force) {
        if (-not $directory.PSIsContainer -or $directory.Name -notmatch '^attempt-([0-9]{4,10})$' -or
            ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Unexpected entry in attempts directory: $($directory.Name)"
        }
        $attemptNumber = [int]$Matches[1]
        if ($directory.Name -ne ('attempt-{0:D4}' -f $attemptNumber)) {
            throw "Non-canonical attempt directory name: $($directory.Name)"
        }
        $summaryName = if ($ExecutionMode -eq 'interactive') { 'interactive-validation-summary.json' } else { 'scheduled-collection.json' }
        $summaryPath = Join-Path $directory.FullName $summaryName
        if (-not (Test-Path -LiteralPath $summaryPath -PathType Leaf)) { continue }
        $summaryPath = Assert-Phase0EntryControlledPath -ControlledRoot $attemptsRoot -Path $summaryPath -Expected File
        $summary = [System.IO.File]::ReadAllText($summaryPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        if ($summary.campaign_id -ne $CampaignId -or $summary.validation_id -ne $ValidationId -or $summary.result -ne 'passed') { continue }
        if ($ExecutionMode -eq 'interactive') {
            if ([int]$summary.collection_attempt -ne $attemptNumber) { throw 'Interactive summary attempt binding is invalid' }
            $resultAttempt = $attemptNumber
            $relative = "ocr/interactive/$ValidationId"
        }
        else {
            if ($summary.final -ne $true -or [int]$summary.collection_attempt -ne $attemptNumber) {
                throw 'Scheduled summary attempt binding is invalid'
            }
            $resultAttempt = [int]$summary.install_attempt
            $relative = "run/scheduled/output/$ValidationId"
        }
        $resultRoot = Join-Path $attemptsRoot ('attempt-{0:D4}' -f $resultAttempt)
        $candidate = Join-Path $resultRoot $relative
        $candidate = Assert-Phase0EntryControlledPath -ControlledRoot $attemptsRoot -Path $candidate -Expected Directory
        $null = Test-Phase0EvidenceTree -PackageRoot $PackageRoot -Path $candidate
        $resultDirectories += $candidate
    }
    if ($resultDirectories.Count -ne 1) {
        throw "Expected exactly one passed $ExecutionMode result directory for $ValidationId"
    }
    return [string]$resultDirectories[0]
}

try {
    if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
        $candidatePackageRoot = $PSScriptRoot
        if (-not (Test-Path -LiteralPath (Join-Path $candidatePackageRoot 'SHA256SUMS.txt') -PathType Leaf)) {
            $candidatePackageRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
        }
        $PackageRoot = $candidatePackageRoot
    }
    $PackageRoot = (Resolve-Path -LiteralPath $PackageRoot).Path
    $rootResolved = $true

    Import-Module (Join-Path $PSScriptRoot 'Phase0.Package.psm1') -Force
    Import-Module (Join-Path $PSScriptRoot 'Phase0.Scheduler.psm1') -Force
    $moduleImported = $true
    $campaignLock = Enter-Phase0CampaignLock -PackageRoot $PackageRoot -CampaignId $CampaignId
    if ($Action -in @('Preflight', 'Prepare', 'SelfTest')) {
        $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId
    }
    $campaignSecurityRoot = Join-Path $PackageRoot "work/campaigns/$CampaignId"
    if (Test-Path -LiteralPath $campaignSecurityRoot -PathType Container) {
        $null = Test-Phase0CampaignSecurityPath -Path $campaignSecurityRoot
    }

    switch ($Action) {
        'Preflight' {
            Invoke-Phase0Preflight -PackageRoot $PackageRoot -CampaignId $CampaignId -Attempt $attempt.number
        }
        'Prepare' {
            Invoke-Phase0Prepare -PackageRoot $PackageRoot -CampaignId $CampaignId -Attempt $attempt.number
        }
        'SelfTest' {
            Invoke-Phase0SelfTest -PackageRoot $PackageRoot -CampaignId $CampaignId -Attempt $attempt.number
        }
        'RunInteractive' {
            Invoke-InteractiveValidation -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId
        }
        'InstallScheduledTask' {
            Install-Phase0ScheduledTask -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -Credential $Credential
        }
        'CollectScheduledTask' {
            Collect-Phase0ScheduledTask -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId
        }
        'ExportEvidence' {
            Assert-Phase0EntryIdentifier -Value $InteractiveId -Name 'InteractiveId'
            Assert-Phase0EntryIdentifier -Value $ScheduledId -Name 'ScheduledId'
            $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
            if ($state.state -ne 'SCHEDULED_OCR_PASSED' -or
                $state.interactive_validation_id -ne $InteractiveId -or
                $state.scheduled_validation_id -ne $ScheduledId) {
                throw 'ExportEvidence requires the matching passed interactive and scheduled validations'
            }
            $interactiveResults = Get-Phase0EntryResultsDirectory -PackageRoot $PackageRoot -CampaignId $CampaignId `
                -ValidationId $InteractiveId -ExecutionMode interactive
            $scheduledResults = Get-Phase0EntryResultsDirectory -PackageRoot $PackageRoot -CampaignId $CampaignId `
                -ValidationId $ScheduledId -ExecutionMode scheduled
            $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId
            $exportRelative = "$($attempt.relative)/export"
            $exportDir = New-Phase0ProtectedDirectory -PackageRoot $PackageRoot -RelativePath $exportRelative
            $readinessPath = Join-Path $exportDir 'ocr-readiness.md'
            $reviewBundlePath = Join-Path $exportDir 'review-bundle.zip'
            $portablePython = Join-Path $PackageRoot 'runtime/python/python.exe'
            $projectRoot = Get-Phase0EntryProjectRoot -PackageRoot $PackageRoot
            $originalPythonPath = $env:PYTHONPATH
            try {
                $env:PYTHONPATH = Join-Path $projectRoot 'src'
                & $portablePython -m umi_web_spike.cli build-ocr-readiness --campaign-id $CampaignId `
                    --interactive-dir $interactiveResults --scheduled-dir $scheduledResults --output $readinessPath | Out-Host
                if ($LASTEXITCODE -ne 0) { throw "OCR readiness report failed: $LASTEXITCODE" }
                & $portablePython -m umi_web_spike.cli export-review-bundle --campaign-id $CampaignId `
                    --interactive-dir $interactiveResults --scheduled-dir $scheduledResults --output $reviewBundlePath | Out-Host
                if ($LASTEXITCODE -ne 0) { throw "Review bundle export failed: $LASTEXITCODE" }
            }
            finally { $env:PYTHONPATH = $originalPythonPath }
            $campaignRoot = Join-Path $PackageRoot "work/campaigns/$CampaignId"
            foreach ($name in @('e10', 'reports')) {
                $path = New-Phase0ProtectedDirectory -PackageRoot $PackageRoot `
                    -RelativePath "work/campaigns/$CampaignId/$name"
                $null = Assert-Phase0EntryControlledPath -ControlledRoot $campaignRoot -Path $path -Expected Directory
                $null = Test-Phase0CampaignSecurityPath -Path $path
            }
            $relative = "$($attempt.relative)/export/review-bundle.zip"
            $null = Set-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId `
                -NewState 'OCR_READY_E10_PENDING' -Attempt $attempt.number -EvidenceRelativePath $relative
            [Console]::Out.WriteLine("OCR readiness report: $readinessPath")
            [Console]::Out.WriteLine("Redacted review bundle: $reviewBundlePath")
            [Console]::Out.WriteLine("Scheduled OCR results: $scheduledResults")
        }
        'ResumeE10' {
            $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
            if ($state.state -ne 'OCR_READY_E10_PENDING' -or [string]::IsNullOrWhiteSpace([string]$state.scheduled_validation_id)) {
                throw 'ResumeE10 requires OCR_READY_E10_PENDING with a bound scheduled validation ID'
            }
            $campaignRoot = Join-Path $PackageRoot "work/campaigns/$CampaignId"
            $controlledE10Root = Join-Path $campaignRoot 'e10'
            $null = Assert-Phase0EntryControlledPath -ControlledRoot $campaignRoot -Path $controlledE10Root -Expected Directory
            $null = Test-Phase0CampaignSecurityPath -Path $controlledE10Root
            $E10EvidencePath = Assert-Phase0EntryControlledPath -ControlledRoot $controlledE10Root -Path $E10EvidencePath -Expected File
            $portablePython = Join-Path $PackageRoot 'runtime/python/python.exe'
            $projectRoot = Get-Phase0EntryProjectRoot -PackageRoot $PackageRoot
            $validatorCode = @'
import json
import sys
from pathlib import Path
from umi_web_spike.e10_evidence import E10Evidence

evidence_path = Path(sys.argv[1]).resolve(strict=True)
controlled_root = Path(sys.argv[2]).resolve(strict=True)
evidence_path.relative_to(controlled_root)
evidence = E10Evidence.from_dict(json.loads(evidence_path.read_text(encoding="utf-8")))
if evidence.validation_id != sys.argv[3]:
    raise ValueError("E10 validation_id must match scheduled OCR validation_id")
Path(evidence.official_document_path).resolve(strict=True).relative_to(controlled_root)
'@
            $originalPythonPath = $env:PYTHONPATH
            try {
                $env:PYTHONPATH = Join-Path $projectRoot 'src'
                & $portablePython -c $validatorCode $E10EvidencePath $controlledE10Root $state.scheduled_validation_id | Out-Host
                $nativeExitCode = [int]$LASTEXITCODE
            }
            finally { $env:PYTHONPATH = $originalPythonPath }
            if ($nativeExitCode -ne 0) { exit $nativeExitCode }
            $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId
            $evidenceCopy = Join-Path $attempt.root 'e10.json'
            [System.IO.File]::Copy($E10EvidencePath, $evidenceCopy, $false)
            $relative = "$($attempt.relative)/e10.json"
            $null = Set-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId `
                -NewState 'E10_READY' -Attempt $attempt.number -EvidenceRelativePath $relative
        }
        'BuildFinalReport' {
            $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
            if ($state.state -notin @('OCR_READY_E10_PENDING', 'E10_READY')) {
                throw 'BuildFinalReport requires OCR_READY_E10_PENDING or E10_READY'
            }
            $campaignRoot = Join-Path $PackageRoot "work/campaigns/$CampaignId"
            $controlledE10Root = Join-Path $campaignRoot 'e10'
            $controlledReportsRoot = Join-Path $campaignRoot 'reports'
            $null = Assert-Phase0EntryControlledPath -ControlledRoot $campaignRoot -Path $controlledE10Root -Expected Directory
            $null = Assert-Phase0EntryControlledPath -ControlledRoot $campaignRoot -Path $controlledReportsRoot -Expected Directory
            $null = Test-Phase0CampaignSecurityPath -Path $controlledE10Root
            $null = Test-Phase0CampaignSecurityPath -Path $controlledReportsRoot
            $E10EvidencePath = Assert-Phase0EntryControlledPath -ControlledRoot $controlledE10Root -Path $E10EvidencePath -Expected MissingOrFile
            $FinalReportPath = Assert-Phase0EntryControlledPath -ControlledRoot $controlledReportsRoot -Path $FinalReportPath -Expected MissingOrFile
            if (Test-Path -LiteralPath $FinalReportPath) { throw 'Final report output already exists' }
            if ($state.state -eq 'OCR_READY_E10_PENDING' -and (Test-Path -LiteralPath $E10EvidencePath -PathType Leaf)) {
                throw 'Run ResumeE10 before building a successful final report'
            }
            if ($state.state -eq 'E10_READY') {
                $normalizedEvidenceRelative = ([string]$state.evidence_relative_path).Replace('\', '/')
                if (-not $normalizedEvidenceRelative.EndsWith('/e10.json', [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw 'E10_READY state does not reference the ResumeE10 evidence snapshot'
                }
                $recordedE10Evidence = Join-Path $PackageRoot ($normalizedEvidenceRelative.Replace('/', '\'))
                $recordedE10Evidence = Assert-Phase0EntryControlledPath -ControlledRoot $campaignRoot `
                    -Path $recordedE10Evidence -Expected File
                $currentE10Digest = (Get-FileHash -LiteralPath $E10EvidencePath -Algorithm SHA256).Hash
                $recordedE10Digest = (Get-FileHash -LiteralPath $recordedE10Evidence -Algorithm SHA256).Hash
                if (-not $currentE10Digest.Equals($recordedE10Digest, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw 'E10 evidence changed after ResumeE10'
                }
            }
            $expectedScheduledResults = Get-Phase0EntryResultsDirectory -PackageRoot $PackageRoot -CampaignId $CampaignId `
                -ValidationId $state.scheduled_validation_id -ExecutionMode scheduled
            $ScheduledResultsDir = Assert-Phase0EntryControlledPath -ControlledRoot $campaignRoot -Path $ScheduledResultsDir -Expected Directory
            $null = Test-Phase0EvidenceTree -PackageRoot $PackageRoot -Path $ScheduledResultsDir
            if (-not $ScheduledResultsDir.Equals($expectedScheduledResults, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw 'ScheduledResultsDir does not match the campaign scheduled validation'
            }
            $portablePython = Join-Path $PackageRoot 'runtime/python/python.exe'
            $projectRoot = Get-Phase0EntryProjectRoot -PackageRoot $PackageRoot
            $originalPythonPath = $env:PYTHONPATH
            try {
                $env:PYTHONPATH = Join-Path $projectRoot 'src'
                & "$PackageRoot\runtime\python\python.exe" -m umi_web_spike.cli build-report --results-dir $ScheduledResultsDir --e10 $E10EvidencePath --output $FinalReportPath | Out-Host
                $nativeExitCode = [int]$LASTEXITCODE
            }
            finally { $env:PYTHONPATH = $originalPythonPath }
            if ($nativeExitCode -ne 0) { exit $nativeExitCode }
            if ($state.state -ne 'E10_READY') { throw 'ResumeE10 is required before Phase 0 can pass' }
            $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId
            $reportCopy = Join-Path $attempt.root 'final-report.md'
            [System.IO.File]::Copy($FinalReportPath, $reportCopy, $false)
            $relative = "$($attempt.relative)/final-report.md"
            $null = Set-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId `
                -NewState 'PHASE_0_PASSED' -Attempt $attempt.number -EvidenceRelativePath $relative
        }
        'RemoveScheduledTask' {
            Remove-Phase0ScheduledTask -PackageRoot $PackageRoot -CampaignId $CampaignId `
                -ValidationId $ValidationId -ConfirmCleanup:$ConfirmCleanup
        }
    }
    $exitCode = 0
}
catch {
    $originalError = $_
    if ($moduleImported -and $rootResolved -and
        $Action -in @('Preflight', 'Prepare', 'SelfTest')) {
        try {
            $failedState = @{
                'Preflight'             = 'PREFLIGHT_FAILED'
                'Prepare'               = 'PREPARE_FAILED'
                'SelfTest'              = 'SELF_TEST_FAILED'
            }[$Action]
            if ($null -eq $campaignLock) {
                $campaignLock = Enter-Phase0CampaignLock -PackageRoot $PackageRoot -CampaignId $CampaignId
            }
            if ($null -eq $attempt) {
                $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId
            }
            $failureRelativePath = Write-Phase0Failure -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -Action $Action -ErrorRecord $originalError -Attempt $attempt.number
            $stateParameters = @{
                PackageRoot = $PackageRoot; CampaignId = $CampaignId; NewState = $failedState
                Attempt = $attempt.number; EvidenceRelativePath = $failureRelativePath
            }
            $null = Set-Phase0State @stateParameters
        }
        catch {
            [Console]::Error.WriteLine("Failure diagnostic or state publication also failed: $($_.Exception.GetType().FullName)")
        }
    }
    Write-Error -ErrorRecord $originalError -ErrorAction Continue
    $exitCode = 1
}
finally {
    if ($null -ne $campaignLock) {
        Exit-Phase0CampaignLock -Lock $campaignLock
    }
}

exit $exitCode
