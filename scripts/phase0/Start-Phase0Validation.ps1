param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        'Preflight', 'Prepare', 'SelfTest', 'RunInteractive',
        'InstallScheduledTask', 'CollectScheduledTask', 'RemoveScheduledTask'
    )]
    [string]$Action,
    [string]$PackageRoot = '',
    [string]$CampaignId = ('campaign-' + [guid]::NewGuid().ToString('N')),
    [string]$ValidationId = ([guid]::NewGuid().ToString('N')),
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
    if ($Action -notin @('CollectScheduledTask', 'RemoveScheduledTask')) {
        $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId
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
            Invoke-InteractiveValidation -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -Attempt $attempt
        }
        'InstallScheduledTask' {
            Install-Phase0ScheduledTask -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -Attempt $attempt -Credential $Credential
        }
        'CollectScheduledTask' {
            Collect-Phase0ScheduledTask -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId
        }
        'RemoveScheduledTask' {
            Remove-Phase0ScheduledTask -ValidationId $ValidationId -ConfirmCleanup:$ConfirmCleanup
        }
    }
    $exitCode = 0
}
catch {
    $originalError = $_
    if ($moduleImported -and $rootResolved -and
        $originalError.Exception.Data['Phase0StatePublished'] -ne $true -and
        $Action -ne 'RemoveScheduledTask') {
        try {
            $failedState = @{
                'Preflight'             = 'PREFLIGHT_FAILED'
                'Prepare'               = 'PREPARE_FAILED'
                'SelfTest'              = 'SELF_TEST_FAILED'
                'RunInteractive'        = 'INTERACTIVE_OCR_FAILED'
                'InstallScheduledTask'  = 'SCHEDULED_OCR_FAILED'
                'CollectScheduledTask'  = 'SCHEDULED_OCR_FAILED'
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
            if ($Action -eq 'RunInteractive') {
                $stateParameters.ValidationKind = 'Interactive'
                $stateParameters.ValidationId = $ValidationId
            }
            elseif ($Action -in @('InstallScheduledTask', 'CollectScheduledTask')) {
                $stateParameters.ValidationKind = 'Scheduled'
                $stateParameters.ValidationId = $ValidationId
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
