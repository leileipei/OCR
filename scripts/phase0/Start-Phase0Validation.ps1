param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Preflight', 'Prepare', 'SelfTest')]
    [string]$Action,
    [string]$PackageRoot = '',
    [string]$CampaignId = ('campaign-' + [guid]::NewGuid().ToString('N')),
    [string]$ValidationId = ([guid]::NewGuid().ToString('N'))
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
    $moduleImported = $true
    $campaignLock = Enter-Phase0CampaignLock -PackageRoot $PackageRoot -CampaignId $CampaignId
    $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId

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
    }
    $exitCode = 0
}
catch {
    $originalError = $_
    if ($moduleImported -and $rootResolved) {
        try {
            if ($null -eq $campaignLock) {
                $campaignLock = Enter-Phase0CampaignLock -PackageRoot $PackageRoot -CampaignId $CampaignId
            }
            if ($null -eq $attempt) {
                $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId
            }
            $failureRelativePath = Write-Phase0Failure -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -Action $Action -ErrorRecord $originalError -Attempt $attempt.number
            $failedState = @{
                'Preflight' = 'PREFLIGHT_FAILED'
                'Prepare'   = 'PREPARE_FAILED'
                'SelfTest'  = 'SELF_TEST_FAILED'
            }[$Action]
            $null = Set-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId -NewState $failedState -Attempt $attempt.number -EvidenceRelativePath $failureRelativePath
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
