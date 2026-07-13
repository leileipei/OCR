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

if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
    $candidatePackageRoot = $PSScriptRoot
    if (-not (Test-Path -LiteralPath (Join-Path $candidatePackageRoot 'SHA256SUMS.txt') -PathType Leaf)) {
        $candidatePackageRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
    }
    $PackageRoot = $candidatePackageRoot
}
$PackageRoot = (Resolve-Path -LiteralPath $PackageRoot).Path

Import-Module (Join-Path $PSScriptRoot 'Phase0.Package.psm1') -Force

try {
    switch ($Action) {
        'Preflight' {
            Invoke-Phase0Preflight -PackageRoot $PackageRoot -CampaignId $CampaignId
        }
        'Prepare' {
            Invoke-Phase0Prepare -PackageRoot $PackageRoot -CampaignId $CampaignId
        }
        'SelfTest' {
            Invoke-Phase0SelfTest -PackageRoot $PackageRoot -CampaignId $CampaignId
        }
    }
    exit 0
}
catch {
    $originalError = $_
    $failureRelativePath = $null
    try {
        $failureRelativePath = Write-Phase0Failure -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -Action $Action -ErrorRecord $originalError
        $failedState = @{
            'Preflight' = 'PREFLIGHT_FAILED'
            'Prepare'   = 'PREPARE_FAILED'
            'SelfTest'  = 'SELF_TEST_FAILED'
        }[$Action]
        $null = Set-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId -NewState $failedState -EvidenceRelativePath $failureRelativePath
    }
    catch {
        Write-Warning "Failure diagnostic or state publication also failed: $($_.Exception.GetType().FullName)"
    }
    Write-Error -ErrorRecord $originalError -ErrorAction Continue
    exit 1
}
