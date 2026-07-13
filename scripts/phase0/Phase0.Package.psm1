Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$AllowedTransitions = @{
    'NEW'                       = @('PREFLIGHT_PASSED', 'PREFLIGHT_FAILED')
    'PREFLIGHT_FAILED'          = @('PREFLIGHT_PASSED', 'PREFLIGHT_FAILED')
    'PREFLIGHT_PASSED'          = @('PREPARED', 'PREPARE_FAILED')
    'PREPARE_FAILED'            = @('PREPARED', 'PREPARE_FAILED')
    'PREPARED'                  = @('SELF_TEST_PASSED', 'SELF_TEST_FAILED')
    'SELF_TEST_FAILED'          = @('SELF_TEST_PASSED', 'SELF_TEST_FAILED')
    'SELF_TEST_PASSED'          = @('INTERACTIVE_OCR_PASSED', 'INTERACTIVE_OCR_FAILED')
    'INTERACTIVE_OCR_FAILED'    = @('INTERACTIVE_OCR_PASSED', 'INTERACTIVE_OCR_FAILED')
    'INTERACTIVE_OCR_PASSED'    = @('SCHEDULED_OCR_PASSED', 'SCHEDULED_OCR_FAILED')
    'SCHEDULED_OCR_FAILED'      = @('SCHEDULED_OCR_PASSED', 'SCHEDULED_OCR_FAILED')
    'SCHEDULED_OCR_PASSED'      = @('OCR_READY_E10_PENDING')
    'OCR_READY_E10_PENDING'     = @('E10_READY')
    'E10_READY'                 = @('PHASE_0_PASSED')
}

function Assert-Phase0Identifier {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
        throw "$Name must contain only safe identifier characters and be at most 128 characters"
    }
}

function Get-Phase0CanonicalRoot {
    param([Parameter(Mandatory = $true)][string]$PackageRoot)

    if ($PackageRoot -match '[\x00-\x1F\x7F]') {
        throw 'Package path contains control characters'
    }
    if (-not (Test-Path -LiteralPath $PackageRoot -PathType Container)) {
        throw "Package root does not exist: $PackageRoot"
    }
    return [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $PackageRoot).Path).TrimEnd('\', '/')
}

function Assert-Phase0NoReparsePoint {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Candidate
    )

    $canonicalRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $current = [System.IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    while (-not $current.Equals($canonicalRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Path contains a reparse point: $current"
            }
        }
        $parent = [System.IO.Path]::GetDirectoryName($current)
        if ([string]::IsNullOrEmpty($parent) -or $parent -eq $current) {
            throw "Unable to prove path containment: $Candidate"
        }
        $current = $parent.TrimEnd('\', '/')
    }
}

function Resolve-Phase0ContainedPath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath) -or
        [System.IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath -match '[\x00-\x1F\x7F]') {
        throw "Unsafe relative path: $RelativePath"
    }
    $segments = $RelativePath -split '[\\/]'
    if ($segments -contains '' -or $segments -contains '.' -or $segments -contains '..') {
        throw "Unsafe relative path: $RelativePath"
    }
    $invalidNameCharacters = [System.IO.Path]::GetInvalidFileNameChars()
    foreach ($segment in $segments) {
        if ($segment.IndexOfAny($invalidNameCharacters) -ge 0 -or
            $segment.EndsWith('.') -or $segment.EndsWith(' ') -or
            $segment -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$') {
            throw "Unsafe relative path segment: $segment"
        }
    }

    $canonicalRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $canonicalRoot ($RelativePath -replace '/', '\')))
    $rootPrefix = $canonicalRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes package root: $RelativePath"
    }
    Assert-Phase0NoReparsePoint -Root $canonicalRoot -Candidate $candidate
    return $candidate
}

function ConvertTo-Phase0RelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $canonicalRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $canonicalPath = [System.IO.Path]::GetFullPath($Path)
    $rootPrefix = $canonicalRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $canonicalPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside package root: $Path"
    }
    return $canonicalPath.Substring($rootPrefix.Length).Replace('\', '/')
}

function Write-AtomicUtf8Json {
    param(
        [Parameter(Mandatory = $true)][string]$FinalPath,
        [Parameter(Mandatory = $true)]$Value,
        [switch]$Replace
    )

    $parent = Split-Path -Parent $FinalPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $parent -Force
    }
    if ((Test-Path $FinalPath) -and -not $Replace) {
        throw "Refusing to overwrite $FinalPath"
    }

    $TempPath = "$FinalPath.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        $json = $Value | ConvertTo-Json -Depth 20
        $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($TempPath, ($json + [Environment]::NewLine), $utf8WithoutBom)
        if (Test-Path $FinalPath) {
            [System.IO.File]::Replace($TempPath, $FinalPath, $null)
        }
        else {
            Move-Item -LiteralPath $TempPath -Destination $FinalPath
        }
    }
    finally {
        if (Test-Path -LiteralPath $TempPath) {
            Remove-Item -LiteralPath $TempPath -Force
        }
    }
}

function Get-Phase0CampaignRoot {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId
    )

    Assert-Phase0Identifier -Value $CampaignId -Name 'CampaignId'
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    return Resolve-Phase0ContainedPath -Root $root -RelativePath "work/campaigns/$CampaignId"
}

function Assert-Phase0EvidencePath {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId,
        [Parameter(Mandatory = $true)][int]$Attempt,
        [Parameter(Mandatory = $true)][string]$EvidenceRelativePath,
        [switch]$RequireExisting
    )

    Assert-Phase0Identifier -Value $CampaignId -Name 'CampaignId'
    if ($Attempt -lt 1) {
        throw 'Evidence attempt must be positive'
    }
    $normalizedEvidencePath = $EvidenceRelativePath.Replace('\', '/')
    $expectedEvidencePrefix = "work/campaigns/$CampaignId/attempts/attempt-$('{0:D4}' -f $Attempt)/"
    if (-not $normalizedEvidencePath.StartsWith($expectedEvidencePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'State evidence must belong to the matching campaign attempt'
    }
    $path = Resolve-Phase0ContainedPath -Root $PackageRoot -RelativePath $normalizedEvidencePath
    if ($RequireExisting -and -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "State evidence does not exist: $EvidenceRelativePath"
    }
    return $path
}

function Get-Phase0State {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId
    )

    $campaignRoot = Get-Phase0CampaignRoot -PackageRoot $PackageRoot -CampaignId $CampaignId
    $statePath = Join-Path $campaignRoot 'state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return [pscustomobject][ordered]@{
            campaign_id             = $CampaignId
            interactive_validation_id = $null
            scheduled_validation_id = $null
            state                   = 'NEW'
            utc                     = $null
            attempt                 = 0
            evidence_relative_path  = $null
        }
    }

    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedProperties = @(
        'attempt',
        'campaign_id',
        'evidence_relative_path',
        'interactive_validation_id',
        'scheduled_validation_id',
        'state',
        'utc'
    )
    $actualProperties = @($state.PSObject.Properties.Name | Sort-Object)
    $propertyDifferences = @(Compare-Object -ReferenceObject $expectedProperties -DifferenceObject $actualProperties)
    if ($propertyDifferences.Count -ne 0) {
        throw 'Campaign state contains unexpected or missing fields'
    }
    if ($state.campaign_id -ne $CampaignId -or
        (-not $AllowedTransitions.ContainsKey([string]$state.state) -and $state.state -ne 'PHASE_0_PASSED') -or
        ($state.attempt -isnot [int] -and $state.attempt -isnot [System.Int64]) -or
        $state.attempt -lt 1 -or $state.attempt -gt [int]::MaxValue) {
        throw 'Campaign state is invalid'
    }
    $parsedUtc = [DateTime]::MinValue
    if (-not [DateTime]::TryParse(
            [string]$state.utc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind,
            [ref]$parsedUtc)) {
        throw 'Campaign state UTC timestamp is invalid'
    }
    foreach ($validationId in @($state.interactive_validation_id, $state.scheduled_validation_id)) {
        if ($null -ne $validationId) {
            Assert-Phase0Identifier -Value ([string]$validationId) -Name 'ValidationId'
        }
    }
    if ($null -ne $state.interactive_validation_id -and
        $null -ne $state.scheduled_validation_id -and
        $state.interactive_validation_id -eq $state.scheduled_validation_id) {
        throw 'Campaign validation IDs must be different'
    }
    $null = Assert-Phase0EvidencePath -PackageRoot (Get-Phase0CanonicalRoot $PackageRoot) -CampaignId $CampaignId -Attempt ([int]$state.attempt) -EvidenceRelativePath ([string]$state.evidence_relative_path) -RequireExisting
    return $state
}

function Assert-Phase0CanTransition {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId,
        [Parameter(Mandatory = $true)][string]$NewState
    )

    $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
    $currentState = [string]$state.state
    if (-not $AllowedTransitions.ContainsKey($currentState) -or
        $AllowedTransitions[$currentState] -notcontains $NewState) {
        throw "Invalid Phase 0 state transition: $currentState -> $NewState"
    }
    return $state
}

function Get-Phase0AttemptContext {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId
    )

    $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
    $attempt = [int]$state.attempt + 1
    $campaignRoot = Get-Phase0CampaignRoot -PackageRoot $PackageRoot -CampaignId $CampaignId
    $attemptRoot = Join-Path (Join-Path $campaignRoot 'attempts') ('attempt-{0:D4}' -f $attempt)
    if (-not (Test-Path -LiteralPath $attemptRoot -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $attemptRoot -Force
    }
    return [pscustomobject]@{
        number = $attempt
        root = $attemptRoot
    }
}

function Set-Phase0State {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId,
        [Parameter(Mandatory = $true)][string]$NewState,
        [Parameter(Mandatory = $true)][string]$EvidenceRelativePath,
        [int]$Attempt = 0,
        [ValidateSet('None', 'Interactive', 'Scheduled')][string]$ValidationKind = 'None',
        [string]$ValidationId = ''
    )

    Assert-Phase0Identifier -Value $CampaignId -Name 'CampaignId'
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $state = Assert-Phase0CanTransition -PackageRoot $root -CampaignId $CampaignId -NewState $NewState

    $nextAttempt = [int]$state.attempt + 1
    if ($Attempt -eq 0) {
        $Attempt = $nextAttempt
    }
    if ($Attempt -ne $nextAttempt) {
        throw "Attempt must be the next campaign attempt: $nextAttempt"
    }
    $null = Assert-Phase0EvidencePath -PackageRoot $root -CampaignId $CampaignId -Attempt $Attempt -EvidenceRelativePath $EvidenceRelativePath -RequireExisting

    $interactiveValidationId = $state.interactive_validation_id
    $scheduledValidationId = $state.scheduled_validation_id
    if ($ValidationKind -ne 'None') {
        Assert-Phase0Identifier -Value $ValidationId -Name 'ValidationId'
        if ($ValidationKind -eq 'Interactive') {
            if ($null -ne $interactiveValidationId -and $interactiveValidationId -ne $ValidationId) {
                throw 'Interactive validation ID is already bound to this campaign'
            }
            $interactiveValidationId = $ValidationId
        }
        else {
            if ($null -ne $scheduledValidationId -and $scheduledValidationId -ne $ValidationId) {
                throw 'Scheduled validation ID is already bound to this campaign'
            }
            $scheduledValidationId = $ValidationId
        }
        if ($null -ne $interactiveValidationId -and
            $null -ne $scheduledValidationId -and
            $interactiveValidationId -eq $scheduledValidationId) {
            throw 'Interactive and scheduled validation IDs must be different'
        }
    }

    $newValue = [pscustomobject][ordered]@{
        campaign_id               = $CampaignId
        interactive_validation_id = $interactiveValidationId
        scheduled_validation_id   = $scheduledValidationId
        state                     = $NewState
        utc                       = [DateTime]::UtcNow.ToString('o')
        attempt                   = $Attempt
        evidence_relative_path    = $EvidenceRelativePath.Replace('\', '/')
    }

    $campaignRoot = Get-Phase0CampaignRoot -PackageRoot $root -CampaignId $CampaignId
    $attemptRoot = Join-Path (Join-Path $campaignRoot 'attempts') ('attempt-{0:D4}' -f $Attempt)
    if (-not (Test-Path -LiteralPath $attemptRoot -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $attemptRoot -Force
    }
    Write-AtomicUtf8Json -FinalPath (Join-Path $attemptRoot 'state-transition.json') -Value $newValue
    Write-AtomicUtf8Json -FinalPath (Join-Path $campaignRoot 'state.json') -Value $newValue -Replace
    return $newValue
}

function Write-Phase0Failure {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId,
        [Parameter(Mandatory = $true)][string]$ValidationId,
        [Parameter(Mandatory = $true)][string]$Action,
        [Parameter(Mandatory = $true)][System.Management.Automation.ErrorRecord]$ErrorRecord
    )

    Assert-Phase0Identifier -Value $CampaignId -Name 'CampaignId'
    Assert-Phase0Identifier -Value $ValidationId -Name 'ValidationId'
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $attempt = Get-Phase0AttemptContext -PackageRoot $root -CampaignId $CampaignId
    $failurePath = Join-Path $attempt.root 'failure.json'
    $diagnostic = [pscustomobject][ordered]@{
        action             = $Action
        campaign_id        = $CampaignId
        validation_id      = $ValidationId
        exception_type     = $ErrorRecord.Exception.GetType().FullName
        script_stack_trace = $ErrorRecord.ScriptStackTrace
        windows_version    = [Environment]::OSVersion.VersionString
        powershell_version = $PSVersionTable.PSVersion.ToString()
        process_id         = $PID
        SESSIONNAME        = $env:SESSIONNAME
    }
    Write-AtomicUtf8Json -FinalPath $failurePath -Value $diagnostic
    return ConvertTo-Phase0RelativePath -Root $root -Path $failurePath
}

function Test-Phase0Package {
    param([Parameter(Mandatory = $true)][string]$PackageRoot)

    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $sumsPath = Join-Path $root 'SHA256SUMS.txt'
    if (-not (Test-Path -LiteralPath $sumsPath -PathType Leaf)) {
        throw 'SHA256SUMS.txt is missing'
    }

    $listed = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($line in Get-Content -LiteralPath $sumsPath -Encoding UTF8) {
        if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
            throw 'malformed SHA256SUMS entry'
        }
        $digest = $Matches[1]
        $relative = $Matches[2]
        if ($relative.Contains('\') -or $relative -eq 'SHA256SUMS.txt' -or $relative -eq 'work' -or $relative.StartsWith('work/')) {
            throw "Unsafe SHA256SUMS path: $relative"
        }
        if (-not $listed.Add($relative)) {
            throw "duplicate SHA256SUMS path: $relative"
        }
        $candidate = Resolve-Phase0ContainedPath -Root $root -RelativePath $relative
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "SHA256SUMS missing file: $relative"
        }
        $item = Get-Item -LiteralPath $candidate -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "SHA256SUMS path is a reparse point: $relative"
        }
        $actualDigest = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualDigest -ne $digest) {
            throw "SHA256SUMS digest mismatch: $relative"
        }
    }
    if ($listed.Count -eq 0) {
        throw 'SHA256SUMS.txt must list package files'
    }

    $actual = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($topLevelItem in Get-ChildItem -LiteralPath $root -Force) {
        if ($topLevelItem.Name -eq 'work') {
            continue
        }
        $items = @($topLevelItem)
        if ($topLevelItem.PSIsContainer) {
            if (($topLevelItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Package contains a reparse point: $($topLevelItem.Name)"
            }
            $items += @(Get-ChildItem -LiteralPath $topLevelItem.FullName -Recurse -Force)
        }
        foreach ($item in $items) {
            $relative = ConvertTo-Phase0RelativePath -Root $root -Path $item.FullName
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Package contains a reparse point: $relative"
            }
            if (-not $item.PSIsContainer -and $relative -ne 'SHA256SUMS.txt') {
                $null = $actual.Add($relative)
            }
        }
    }
    if ($actual.Count -ne $listed.Count) {
        throw 'SHA256SUMS file set mismatch'
    }
    foreach ($relative in $actual) {
        if (-not $listed.Contains($relative)) {
            throw 'SHA256SUMS file set mismatch'
        }
    }
    return $true
}

function Get-Phase0SupplyLock {
    param([Parameter(Mandatory = $true)][string]$PackageRoot)

    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $candidates = @(
        'offline-package.lock.json',
        'packaging/offline-package.lock.json',
        'toolkit/packaging/offline-package.lock.json'
    )
    foreach ($relative in $candidates) {
        $candidate = Resolve-Phase0ContainedPath -Root $root -RelativePath $relative
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return Get-Content -LiteralPath $candidate -Raw -Encoding UTF8 | ConvertFrom-Json
        }
    }
    throw 'offline-package.lock.json is missing'
}

function Invoke-Phase0Preflight {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId
    )

    Assert-Phase0Identifier -Value $CampaignId -Name 'CampaignId'
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $null = Assert-Phase0CanTransition -PackageRoot $root -CampaignId $CampaignId -NewState 'PREFLIGHT_PASSED'
    if ($env:OS -ne 'Windows_NT') {
        throw 'Phase 0 preflight requires Windows Server'
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'Phase 0 preflight requires a 64-bit operating system'
    }
    if (-not [Environment]::Is64BitProcess) {
        throw 'Phase 0 preflight requires a 64-bit PowerShell process'
    }
    if ($PSVersionTable.PSVersion -lt [Version]'5.1') {
        throw 'Phase 0 preflight requires PowerShell 5.1 or newer'
    }
    $operatingSystem = Get-CimInstance -ClassName Win32_OperatingSystem
    if ([int]$operatingSystem.ProductType -eq 1) {
        throw 'Phase 0 preflight requires Windows Server, not a client OS'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Phase 0 preflight requires an elevated administrator PowerShell'
    }
    $driveRoot = [System.IO.Path]::GetPathRoot($root)
    $drive = New-Object System.IO.DriveInfo($driveRoot)
    if ($drive.AvailableFreeSpace -lt 5GB) {
        throw 'Phase 0 preflight requires at least 5GB free disk space'
    }
    $null = Test-Phase0Package -PackageRoot $root

    $attempt = Get-Phase0AttemptContext -PackageRoot $root -CampaignId $CampaignId
    $outputPath = Join-Path $attempt.root 'preflight.json'
    $output = [pscustomobject][ordered]@{
        campaign_id          = $CampaignId
        utc                  = [DateTime]::UtcNow.ToString('o')
        windows_caption      = [string]$operatingSystem.Caption
        windows_version      = [string]$operatingSystem.Version
        operating_system_64  = [Environment]::Is64BitOperatingSystem
        powershell_version   = $PSVersionTable.PSVersion.ToString()
        administrator        = $true
        free_disk_bytes      = [int64]$drive.AvailableFreeSpace
        package_integrity    = 'passed'
    }
    Write-AtomicUtf8Json -FinalPath $outputPath -Value $output
    $relative = ConvertTo-Phase0RelativePath -Root $root -Path $outputPath
    $null = Set-Phase0State -PackageRoot $root -CampaignId $CampaignId -NewState 'PREFLIGHT_PASSED' -Attempt $attempt.number -EvidenceRelativePath $relative
    return $output
}

function Invoke-Phase0Prepare {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId
    )

    Assert-Phase0Identifier -Value $CampaignId -Name 'CampaignId'
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $null = Assert-Phase0CanTransition -PackageRoot $root -CampaignId $CampaignId -NewState 'PREPARED'
    $lock = Get-Phase0SupplyLock -PackageRoot $root
    $expectedLayout = [ordered]@{
        archive_root  = 'Umi-OCR_Rapid_v2.1.5'
        data_root     = 'Umi-OCR_Rapid_v2.1.5/UmiOCR-data'
        runtime_python = 'Umi-OCR_Rapid_v2.1.5/UmiOCR-data/runtime/python.exe'
        plugin_root   = 'Umi-OCR_Rapid_v2.1.5/UmiOCR-data/plugins'
        plugin_name   = 'win7_x64_RapidOCR-json'
    }
    foreach ($name in $expectedLayout.Keys) {
        if ([string]$lock.umi_layout.$name -ne [string]$expectedLayout[$name]) {
            throw "Unexpected Umi-OCR layout in supply lock: $name"
        }
    }
    if ([string]$lock.umi.name -ne 'Umi-OCR_Rapid_v2.1.5.7z.exe' -or
        [int64]$lock.umi.size -ne 103369422 -or
        [string]$lock.umi.sha256 -ne '659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722') {
        throw 'Unexpected official Umi-OCR asset lock'
    }

    $UmiAsset = Resolve-Phase0ContainedPath -Root $root -RelativePath ('vendor/' + [string]$lock.umi.name)
    if (-not (Test-Path -LiteralPath $UmiAsset -PathType Leaf)) {
        throw 'Official Umi-OCR asset is missing'
    }
    $asset = Get-Item -LiteralPath $UmiAsset
    if ($asset.Length -ne [int64]$lock.umi.size) {
        throw 'Official Umi-OCR asset size mismatch'
    }
    $assetDigest = (Get-FileHash -LiteralPath $UmiAsset -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($assetDigest -ne [string]$lock.umi.sha256) {
        throw 'Official Umi-OCR asset SHA-256 mismatch'
    }

    $campaignRoot = Get-Phase0CampaignRoot -PackageRoot $root -CampaignId $CampaignId
    $UmiRoot = Join-Path $campaignRoot 'umi'
    if (Test-Path -LiteralPath $UmiRoot) {
        throw "Refusing to overwrite existing Umi extraction: $UmiRoot"
    }
    $null = New-Item -ItemType Directory -Path $UmiRoot -Force
    & $UmiAsset -y "-o$UmiRoot"
    if ($LASTEXITCODE -ne 0) {
        throw "Official Umi-OCR extraction failed: $LASTEXITCODE"
    }

    $runtimePython = Resolve-Phase0ContainedPath -Root $UmiRoot -RelativePath $expectedLayout.runtime_python
    $pluginRoot = Resolve-Phase0ContainedPath -Root $UmiRoot -RelativePath $expectedLayout.plugin_root
    $plugin = Resolve-Phase0ContainedPath -Root $pluginRoot -RelativePath $expectedLayout.plugin_name
    if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf) -or
        -not (Test-Path -LiteralPath $pluginRoot -PathType Container) -or
        -not (Test-Path -LiteralPath $plugin -PathType Container)) {
        throw 'Extracted Umi-OCR Rapid package does not match the locked layout'
    }

    $attempt = Get-Phase0AttemptContext -PackageRoot $root -CampaignId $CampaignId
    $outputPath = Join-Path $attempt.root 'run-context.json'
    $output = [pscustomobject][ordered]@{
        campaign_id             = $CampaignId
        utc                     = [DateTime]::UtcNow.ToString('o')
        umi_asset_sha256        = $assetDigest
        umi_root_relative       = ConvertTo-Phase0RelativePath -Root $root -Path $UmiRoot
        umi_runtime_relative    = ConvertTo-Phase0RelativePath -Root $root -Path $runtimePython
        umi_plugin_relative     = ConvertTo-Phase0RelativePath -Root $root -Path $plugin
    }
    Write-AtomicUtf8Json -FinalPath $outputPath -Value $output
    $relative = ConvertTo-Phase0RelativePath -Root $root -Path $outputPath
    $null = Set-Phase0State -PackageRoot $root -CampaignId $CampaignId -NewState 'PREPARED' -Attempt $attempt.number -EvidenceRelativePath $relative
    return $output
}

function Invoke-Phase0SelfTest {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId
    )

    Assert-Phase0Identifier -Value $CampaignId -Name 'CampaignId'
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $null = Assert-Phase0CanTransition -PackageRoot $root -CampaignId $CampaignId -NewState 'SELF_TEST_PASSED'
    $portablePython = Resolve-Phase0ContainedPath -Root $root -RelativePath 'runtime/python/python.exe'
    $toolkitTests = Resolve-Phase0ContainedPath -Root $root -RelativePath 'toolkit/tests'
    if (-not (Test-Path -LiteralPath $portablePython -PathType Leaf)) {
        throw 'Bundled portable Python runtime is missing'
    }
    if (-not (Test-Path -LiteralPath $toolkitTests -PathType Container)) {
        throw 'Bundled toolkit tests are missing'
    }

    & "$root\runtime\python\python.exe" -m pytest "$root\toolkit\tests" -q
    if ($LASTEXITCODE -ne 0) {
        throw "Portable self-test failed: $LASTEXITCODE"
    }

    $attempt = Get-Phase0AttemptContext -PackageRoot $root -CampaignId $CampaignId
    $outputPath = Join-Path $attempt.root 'self-test.json'
    $output = [pscustomobject][ordered]@{
        campaign_id = $CampaignId
        utc         = [DateTime]::UtcNow.ToString('o')
        result      = 'passed'
        exit_code   = 0
    }
    Write-AtomicUtf8Json -FinalPath $outputPath -Value $output
    $relative = ConvertTo-Phase0RelativePath -Root $root -Path $outputPath
    $null = Set-Phase0State -PackageRoot $root -CampaignId $CampaignId -NewState 'SELF_TEST_PASSED' -Attempt $attempt.number -EvidenceRelativePath $relative
    return $output
}

Export-ModuleMember -Function @(
    'Test-Phase0Package',
    'Invoke-Phase0Preflight',
    'Invoke-Phase0Prepare',
    'Invoke-Phase0SelfTest',
    'Get-Phase0State',
    'Set-Phase0State',
    'Write-Phase0Failure'
)
