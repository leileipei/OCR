Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$AllowedTransitions = @{
    'NEW'                    = @('PREFLIGHT_PASSED', 'PREFLIGHT_FAILED')
    'PREFLIGHT_FAILED'       = @('PREFLIGHT_PASSED', 'PREFLIGHT_FAILED')
    'PREFLIGHT_PASSED'       = @('PREPARED', 'PREPARE_FAILED')
    'PREPARE_FAILED'         = @('PREPARED', 'PREPARE_FAILED')
    'PREPARED'               = @('SELF_TEST_PASSED', 'SELF_TEST_FAILED')
    'SELF_TEST_FAILED'       = @('SELF_TEST_PASSED', 'SELF_TEST_FAILED')
    'SELF_TEST_PASSED'       = @('INTERACTIVE_OCR_PASSED', 'INTERACTIVE_OCR_FAILED')
    'INTERACTIVE_OCR_FAILED' = @('INTERACTIVE_OCR_PASSED', 'INTERACTIVE_OCR_FAILED')
    'INTERACTIVE_OCR_PASSED' = @('SCHEDULED_OCR_PASSED', 'SCHEDULED_OCR_FAILED')
    'SCHEDULED_OCR_FAILED'   = @('SCHEDULED_OCR_PASSED', 'SCHEDULED_OCR_FAILED')
    'SCHEDULED_OCR_PASSED'   = @('OCR_READY_E10_PENDING')
    'OCR_READY_E10_PENDING'  = @('E10_READY')
    'E10_READY'              = @('PHASE_0_PASSED')
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
    $canonicalCandidate = [System.IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $current = $canonicalCandidate
    $isLeaf = $true
    while (-not $current.Equals($canonicalRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Path contains a reparse point: $current"
            }
            if (-not $isLeaf -and -not $item.PSIsContainer) {
                throw "Path ancestor is not a directory: $current"
            }
        }
        $parent = [System.IO.Path]::GetDirectoryName($current)
        if ([string]::IsNullOrEmpty($parent) -or $parent -eq $current) {
            throw "Unable to prove path containment: $Candidate"
        }
        $current = $parent.TrimEnd('\', '/')
        $isLeaf = $false
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

function Ensure-Phase0SafeDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $target = Resolve-Phase0ContainedPath -Root $root -RelativePath $RelativePath
    $current = $root
    foreach ($segment in ($RelativePath -split '[\\/]')) {
        $current = [System.IO.Path]::Combine($current, $segment)
        if ([System.IO.File]::Exists($current)) {
            throw "Runtime directory path is a file: $current"
        }
        if (-not [System.IO.Directory]::Exists($current)) {
            $null = [System.IO.Directory]::CreateDirectory($current)
        }
        Assert-Phase0NoReparsePoint -Root $root -Candidate $current
        $item = Get-Item -LiteralPath $current -Force
        if (-not $item.PSIsContainer) {
            throw "Runtime path is not a directory: $current"
        }
    }
    Assert-Phase0NoReparsePoint -Root $root -Candidate $target
    return $target
}

function Assert-Phase0RuntimeLeaf {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateSet('Missing', 'MissingOrFile', 'File', 'Directory')][string]$Expected = 'MissingOrFile'
    )
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $relative = ConvertTo-Phase0RelativePath -Root $root -Path $Path
    $candidate = Resolve-Phase0ContainedPath -Root $root -RelativePath $relative
    if (Test-Path -LiteralPath $candidate) {
        $item = Get-Item -LiteralPath $candidate -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Runtime leaf is a reparse point: $candidate"
        }
        if ($Expected -eq 'Missing') {
            throw "Runtime leaf already exists: $candidate"
        }
        if ($Expected -eq 'Directory' -and -not $item.PSIsContainer) {
            throw "Runtime leaf is not a directory: $candidate"
        }
        if ($Expected -ne 'Directory' -and $item.PSIsContainer) {
            throw "Runtime leaf is not a file: $candidate"
        }
    }
    elseif ($Expected -eq 'File' -or $Expected -eq 'Directory') {
        throw "Runtime leaf is missing: $candidate"
    }
    return $candidate
}

function Write-Phase0Utf8FileCreateNew {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text
    )
    $stream = New-Object System.IO.FileStream(
        $Path,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    $writer = $null
    try {
        try {
            $writer = New-Object System.IO.StreamWriter($stream, (New-Object System.Text.UTF8Encoding($false)))
            $writer.Write($Text)
            $writer.Flush()
            $stream.Flush($true)
        }
        finally {
            if ($null -ne $writer) {
                $writer.Dispose()
            }
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Write-AtomicUtf8Json {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$FinalPath,
        [Parameter(Mandatory = $true)]$Value,
        [switch]$Replace
    )
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $relative = ConvertTo-Phase0RelativePath -Root $root -Path $FinalPath
    $final = Resolve-Phase0ContainedPath -Root $root -RelativePath $relative
    $parent = [System.IO.Path]::GetDirectoryName($final)
    $parentRelative = ConvertTo-Phase0RelativePath -Root $root -Path $parent
    $null = Ensure-Phase0SafeDirectory -PackageRoot $root -RelativePath $parentRelative
    $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $final -Expected 'MissingOrFile'
    if ((Test-Path -LiteralPath $FinalPath) -and -not $Replace) {
        throw "Refusing to overwrite $FinalPath"
    }

    $temp = "$final.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $temp -Expected 'Missing'
        $json = ($Value | ConvertTo-Json -Depth 20) + [Environment]::NewLine
        Write-Phase0Utf8FileCreateNew -Path $temp -Text $json

        # Re-check the complete parent chain immediately before the atomic publish.
        $null = Ensure-Phase0SafeDirectory -PackageRoot $root -RelativePath $parentRelative
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $temp -Expected 'File'
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $final -Expected 'MissingOrFile'
        if ([System.IO.File]::Exists($final)) {
            if (-not $Replace) {
                throw "Refusing to overwrite $FinalPath"
            }
            [System.IO.File]::Replace($temp, $final, $null)
        }
        else {
            [System.IO.File]::Move($temp, $final)
        }
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $final -Expected 'File'
    }
    finally {
        if ([System.IO.File]::Exists($temp)) {
            $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $temp -Expected 'File'
            [System.IO.File]::Delete($temp)
        }
    }
}

function Get-Phase0CampaignRelativePath {
    param([string]$CampaignId)
    Assert-Phase0Identifier -Value $CampaignId -Name 'CampaignId'
    return "work/campaigns/$CampaignId"
}

function Get-Phase0CampaignRoot {
    param([string]$PackageRoot, [string]$CampaignId)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    return Resolve-Phase0ContainedPath -Root $root -RelativePath (Get-Phase0CampaignRelativePath $CampaignId)
}

function Initialize-Phase0CampaignDirectories {
    param([string]$PackageRoot, [string]$CampaignId)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $campaignRelative = Get-Phase0CampaignRelativePath $CampaignId
    $null = Ensure-Phase0SafeDirectory -PackageRoot $root -RelativePath 'work'
    $null = Ensure-Phase0SafeDirectory -PackageRoot $root -RelativePath 'work/campaigns'
    $null = Ensure-Phase0SafeDirectory -PackageRoot $root -RelativePath $campaignRelative
    $null = Ensure-Phase0SafeDirectory -PackageRoot $root -RelativePath "$campaignRelative/attempts"
    return Resolve-Phase0ContainedPath -Root $root -RelativePath $campaignRelative
}

function Get-Phase0MutexName {
    param([string]$PackageRoot, [string]$CampaignId)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    Assert-Phase0Identifier -Value $CampaignId -Name 'CampaignId'
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant() + '|' + $CampaignId.ToLowerInvariant())
        $digest = $algorithm.ComputeHash($bytes)
    }
    finally {
        $algorithm.Dispose()
    }
    $token = (($digest | ForEach-Object { $_.ToString('x2') }) -join '')
    return "Global\UmiOcrPhase0-$token"
}

function Enter-Phase0CampaignLock {
    param([string]$PackageRoot, [string]$CampaignId)
    $name = Get-Phase0MutexName -PackageRoot $PackageRoot -CampaignId $CampaignId
    $mutex = New-Object System.Threading.Mutex($false, $name)
    $acquired = $false
    try {
        try {
            $acquired = $mutex.WaitOne(30000)
        }
        catch [System.Threading.AbandonedMutexException] {
            $acquired = $true
        }
        if (-not $acquired) {
            throw "Campaign is busy: $CampaignId"
        }
        return [pscustomobject]@{ mutex = $mutex; acquired = $true }
    }
    catch {
        if (-not $acquired) {
            $mutex.Dispose()
        }
        throw
    }
}

function Exit-Phase0CampaignLock {
    param([Parameter(Mandatory = $true)]$Lock)
    if ($Lock.acquired) {
        $Lock.mutex.ReleaseMutex()
        $Lock.acquired = $false
    }
    $Lock.mutex.Dispose()
}

function Get-Phase0State {
    param([string]$PackageRoot, [string]$CampaignId)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $campaignRelative = Get-Phase0CampaignRelativePath $CampaignId
    $campaignRoot = Resolve-Phase0ContainedPath -Root $root -RelativePath $campaignRelative
    if (Test-Path -LiteralPath $campaignRoot) {
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $campaignRoot -Expected 'Directory'
    }
    $statePath = Resolve-Phase0ContainedPath -Root $root -RelativePath "$campaignRelative/state.json"
    if (-not (Test-Path -LiteralPath $statePath)) {
        return [pscustomobject][ordered]@{
            campaign_id               = $CampaignId
            interactive_validation_id = $null
            scheduled_validation_id   = $null
            state                     = 'NEW'
            recorded_at_utc           = $null
            attempt                   = 0
            evidence_relative_path    = $null
        }
    }
    $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $statePath -Expected 'File'
    $raw = [System.IO.File]::ReadAllText($statePath, [System.Text.Encoding]::UTF8)
    $state = $raw | ConvertFrom-Json
    $expectedProperties = @(
        'attempt', 'campaign_id', 'evidence_relative_path', 'interactive_validation_id',
        'recorded_at_utc', 'scheduled_validation_id', 'state'
    ) | Sort-Object
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
    $recordedAt = [string]$state.recorded_at_utc
    $parsedUtc = [DateTime]::MinValue
    if (-not $recordedAt.EndsWith('Z', [System.StringComparison]::Ordinal) -or
        -not [DateTime]::TryParse($recordedAt, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind, [ref]$parsedUtc) -or
        $parsedUtc.Kind -ne [DateTimeKind]::Utc) {
        throw 'Campaign state recorded_at_utc must be UTC with a Z suffix'
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
    $null = Assert-Phase0EvidencePath -PackageRoot $root -CampaignId $CampaignId -Attempt ([int]$state.attempt) -EvidenceRelativePath ([string]$state.evidence_relative_path) -RequireExisting
    return $state
}

function Assert-Phase0EvidencePath {
    param(
        [string]$PackageRoot,
        [string]$CampaignId,
        [int]$Attempt,
        [string]$EvidenceRelativePath,
        [switch]$RequireExisting
    )
    Assert-Phase0Identifier -Value $CampaignId -Name 'CampaignId'
    if ($Attempt -lt 1) { throw 'Evidence attempt must be positive' }
    $normalized = $EvidenceRelativePath.Replace('\', '/')
    $expectedEvidencePrefix = "work/campaigns/$CampaignId/attempts/attempt-$('{0:D4}' -f $Attempt)/"
    if (-not $normalized.StartsWith($expectedEvidencePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'State evidence must belong to the matching campaign attempt'
    }
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $path = Resolve-Phase0ContainedPath -Root $root -RelativePath $normalized
    if ($RequireExisting) {
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $path -Expected 'File'
    }
    return $path
}

function Assert-Phase0CanTransition {
    param([string]$PackageRoot, [string]$CampaignId, [string]$NewState)
    $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
    if (-not $AllowedTransitions.ContainsKey([string]$state.state) -or
        $AllowedTransitions[[string]$state.state] -notcontains $NewState) {
        throw "Invalid Phase 0 state transition: $($state.state) -> $NewState"
    }
    return $state
}

function Get-Phase0DiskAttemptMaximum {
    param([string]$PackageRoot, [string]$CampaignId)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $campaignRelative = Get-Phase0CampaignRelativePath $CampaignId
    $attemptsRoot = Ensure-Phase0SafeDirectory -PackageRoot $root -RelativePath "$campaignRelative/attempts"
    $maximum = 0
    foreach ($item in Get-ChildItem -LiteralPath $attemptsRoot -Force) {
        if (-not $item.PSIsContainer -or
            ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
            $item.Name -notmatch '^attempt-([0-9]{4,10})$') {
            throw "Unexpected entry in attempts directory: $($item.Name)"
        }
        $number = [int]$Matches[1]
        if ($item.Name -ne ('attempt-{0:D4}' -f $number)) {
            throw "Non-canonical attempt directory name: $($item.Name)"
        }
        if ($number -gt $maximum) { $maximum = $number }
    }
    return $maximum
}

function Get-Phase0AttemptContext {
    param([string]$PackageRoot, [string]$CampaignId)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $lock = Enter-Phase0CampaignLock -PackageRoot $root -CampaignId $CampaignId
    try {
        $null = Initialize-Phase0CampaignDirectories -PackageRoot $root -CampaignId $CampaignId
        $state = Get-Phase0State -PackageRoot $root -CampaignId $CampaignId
        $maximum = [Math]::Max([int]$state.attempt, (Get-Phase0DiskAttemptMaximum -PackageRoot $root -CampaignId $CampaignId))
        if ($maximum -ge [int]::MaxValue) { throw 'Campaign attempt space is exhausted' }
        $attempt = $maximum + 1
        $campaignRelative = Get-Phase0CampaignRelativePath $CampaignId
        $attemptRelative = "$campaignRelative/attempts/attempt-$('{0:D4}' -f $attempt)"
        $attemptRoot = Resolve-Phase0ContainedPath -Root $root -RelativePath $attemptRelative
        if (Test-Path -LiteralPath $attemptRoot) {
            throw "Refusing to reuse existing attempt: $attemptRoot"
        }
        $null = Ensure-Phase0SafeDirectory -PackageRoot $root -RelativePath $attemptRelative
        $reservationPath = Resolve-Phase0ContainedPath -Root $root -RelativePath "$attemptRelative/attempt-reserved.json"
        $reservation = [pscustomobject][ordered]@{
            campaign_id     = $CampaignId
            attempt         = $attempt
            recorded_at_utc = [DateTime]::UtcNow.ToString('o')
        }
        try {
            $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $reservationPath -Expected 'Missing'
            Write-Phase0Utf8FileCreateNew -Path $reservationPath -Text (($reservation | ConvertTo-Json -Depth 5) + [Environment]::NewLine)
        }
        catch {
            throw "Refusing to reuse existing attempt reservation: $reservationPath"
        }
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $reservationPath -Expected 'File'
        return [pscustomobject]@{ number = $attempt; root = $attemptRoot; relative = $attemptRelative }
    }
    finally {
        Exit-Phase0CampaignLock -Lock $lock
    }
}

function Get-Phase0ExistingAttemptContext {
    param([string]$PackageRoot, [string]$CampaignId, [int]$Attempt)
    if ($Attempt -lt 1) { throw 'Attempt must be positive' }
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $campaignRelative = Get-Phase0CampaignRelativePath $CampaignId
    $relative = "$campaignRelative/attempts/attempt-$('{0:D4}' -f $Attempt)"
    $attemptRoot = Resolve-Phase0ContainedPath -Root $root -RelativePath $relative
    $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $attemptRoot -Expected 'Directory'
    $reservation = Resolve-Phase0ContainedPath -Root $root -RelativePath "$relative/attempt-reserved.json"
    $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $reservation -Expected 'File'
    $reservationValue = [System.IO.File]::ReadAllText($reservation, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($reservationValue.campaign_id -ne $CampaignId -or [int]$reservationValue.attempt -ne $Attempt) {
        throw 'Attempt reservation does not match the campaign and attempt'
    }
    return [pscustomobject]@{ number = $Attempt; root = $attemptRoot; relative = $relative }
}

function Set-Phase0State {
    param(
        [string]$PackageRoot,
        [string]$CampaignId,
        [string]$NewState,
        [string]$EvidenceRelativePath,
        [int]$Attempt,
        [ValidateSet('None', 'Interactive', 'Scheduled')][string]$ValidationKind = 'None',
        [string]$ValidationId = ''
    )
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $lock = Enter-Phase0CampaignLock -PackageRoot $root -CampaignId $CampaignId
    try {
        $state = Assert-Phase0CanTransition -PackageRoot $root -CampaignId $CampaignId -NewState $NewState
        if ($Attempt -le [int]$state.attempt) {
            throw 'Attempt must be newer than the recorded campaign state'
        }
        $attemptContext = Get-Phase0ExistingAttemptContext -PackageRoot $root -CampaignId $CampaignId -Attempt $Attempt
        $null = Assert-Phase0EvidencePath -PackageRoot $root -CampaignId $CampaignId -Attempt $Attempt -EvidenceRelativePath $EvidenceRelativePath -RequireExisting

        $interactiveId = $state.interactive_validation_id
        $scheduledId = $state.scheduled_validation_id
        if ($ValidationKind -ne 'None') {
            Assert-Phase0Identifier -Value $ValidationId -Name 'ValidationId'
            if ($ValidationKind -eq 'Interactive') {
                if ($null -ne $interactiveId -and $interactiveId -ne $ValidationId) {
                    throw 'Interactive validation ID is already bound to this campaign'
                }
                $interactiveId = $ValidationId
            }
            else {
                if ($null -ne $scheduledId -and $scheduledId -ne $ValidationId) {
                    throw 'Scheduled validation ID is already bound to this campaign'
                }
                $scheduledId = $ValidationId
            }
            if ($null -ne $interactiveId -and $null -ne $scheduledId -and $interactiveId -eq $scheduledId) {
                throw 'Interactive and scheduled validation IDs must be different'
            }
        }
        $newValue = [pscustomobject][ordered]@{
            campaign_id               = $CampaignId
            interactive_validation_id = $interactiveId
            scheduled_validation_id   = $scheduledId
            state                     = $NewState
            recorded_at_utc           = [DateTime]::UtcNow.ToString('o')
            attempt                   = $Attempt
            evidence_relative_path    = $EvidenceRelativePath.Replace('\', '/')
        }
        $transition = Resolve-Phase0ContainedPath -Root $root -RelativePath "$($attemptContext.relative)/state-transition-$NewState.json"
        Write-AtomicUtf8Json -PackageRoot $root -FinalPath $transition -Value $newValue
        $statePath = Resolve-Phase0ContainedPath -Root $root -RelativePath "$(Get-Phase0CampaignRelativePath $CampaignId)/state.json"
        Write-AtomicUtf8Json -PackageRoot $root -FinalPath $statePath -Value $newValue -Replace
        return $newValue
    }
    finally {
        Exit-Phase0CampaignLock -Lock $lock
    }
}

function Write-Phase0Failure {
    param(
        [string]$PackageRoot,
        [string]$CampaignId,
        [string]$ValidationId,
        [string]$Action,
        [System.Management.Automation.ErrorRecord]$ErrorRecord,
        [int]$Attempt = 0
    )
    Assert-Phase0Identifier -Value $ValidationId -Name 'ValidationId'
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    if ($Attempt -eq 0) {
        $attemptContext = Get-Phase0AttemptContext -PackageRoot $root -CampaignId $CampaignId
    }
    else {
        $attemptContext = Get-Phase0ExistingAttemptContext -PackageRoot $root -CampaignId $CampaignId -Attempt $Attempt
    }
    $failurePath = Resolve-Phase0ContainedPath -Root $root -RelativePath "$($attemptContext.relative)/failure.json"
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
    Write-AtomicUtf8Json -PackageRoot $root -FinalPath $failurePath -Value $diagnostic
    return ConvertTo-Phase0RelativePath -Root $root -Path $failurePath
}

function Test-Phase0Package {
    param([string]$PackageRoot)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $sumsPath = Join-Path $root 'SHA256SUMS.txt'
    if (-not (Test-Path -LiteralPath $sumsPath -PathType Leaf)) { throw 'SHA256SUMS.txt is missing' }
    $listed = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($line in Get-Content -LiteralPath $sumsPath -Encoding UTF8) {
        if ($line -notmatch '^([0-9a-f]{64})  (.+)$') { throw 'malformed SHA256SUMS entry' }
        $digest = $Matches[1]
        $relative = $Matches[2]
        if ($relative.Contains('\') -or $relative -eq 'SHA256SUMS.txt' -or $relative -eq 'work' -or $relative.StartsWith('work/')) {
            throw "Unsafe SHA256SUMS path: $relative"
        }
        if (-not $listed.Add($relative)) { throw "duplicate SHA256SUMS path: $relative" }
        $candidate = Resolve-Phase0ContainedPath -Root $root -RelativePath $relative
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "SHA256SUMS missing file: $relative" }
        $actualDigest = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualDigest -ne $digest) { throw "SHA256SUMS digest mismatch: $relative" }
    }
    if ($listed.Count -eq 0) { throw 'SHA256SUMS.txt must list package files' }

    $actual = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($topLevelItem in Get-ChildItem -LiteralPath $root -Force) {
        if ($topLevelItem.Name -eq 'work') {
            if (-not $topLevelItem.PSIsContainer -or ($topLevelItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Runtime work path must be a normal directory'
            }
            continue
        }
        $items = @($topLevelItem)
        if ($topLevelItem.PSIsContainer) {
            if (($topLevelItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Package contains a reparse point: $($topLevelItem.Name)" }
            $items += @(Get-ChildItem -LiteralPath $topLevelItem.FullName -Recurse -Force)
        }
        foreach ($item in $items) {
            $relative = ConvertTo-Phase0RelativePath -Root $root -Path $item.FullName
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Package contains a reparse point: $relative" }
            if (-not $item.PSIsContainer -and $relative -ne 'SHA256SUMS.txt') { $null = $actual.Add($relative) }
        }
    }
    if ($actual.Count -ne $listed.Count) { throw 'SHA256SUMS file set mismatch' }
    foreach ($relative in $actual) {
        if (-not $listed.Contains($relative)) { throw 'SHA256SUMS file set mismatch' }
    }
    return $true
}

function Get-Phase0SupplyLock {
    param([string]$PackageRoot)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    foreach ($relative in @('offline-package.lock.json', 'packaging/offline-package.lock.json', 'toolkit/packaging/offline-package.lock.json')) {
        $candidate = Resolve-Phase0ContainedPath -Root $root -RelativePath $relative
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [System.IO.File]::ReadAllText($candidate, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        }
    }
    throw 'offline-package.lock.json is missing'
}

function Get-Phase0ActionAttempt {
    param([string]$PackageRoot, [string]$CampaignId, [int]$Attempt)
    if ($Attempt -eq 0) { return Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId }
    return Get-Phase0ExistingAttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId -Attempt $Attempt
}

function Invoke-Phase0Preflight {
    param([string]$PackageRoot, [string]$CampaignId, [int]$Attempt = 0)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $lock = Enter-Phase0CampaignLock -PackageRoot $root -CampaignId $CampaignId
    try {
        $null = Assert-Phase0CanTransition -PackageRoot $root -CampaignId $CampaignId -NewState 'PREFLIGHT_PASSED'
        $attempt = Get-Phase0ActionAttempt -PackageRoot $root -CampaignId $CampaignId -Attempt $Attempt
        if ($env:OS -ne 'Windows_NT') { throw 'Phase 0 preflight requires Windows Server' }
        if (-not [Environment]::Is64BitOperatingSystem) { throw 'Phase 0 preflight requires a 64-bit operating system' }
        if (-not [Environment]::Is64BitProcess) { throw 'Phase 0 preflight requires a 64-bit PowerShell process' }
        if ($PSVersionTable.PSVersion -lt [Version]'5.1') { throw 'Phase 0 preflight requires PowerShell 5.1 or newer' }
        $operatingSystem = Get-CimInstance -ClassName Win32_OperatingSystem
        if ([int]$operatingSystem.ProductType -eq 1) { throw 'Phase 0 preflight requires Windows Server, not a client OS' }
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Phase 0 preflight requires an elevated administrator PowerShell' }
        $drive = New-Object System.IO.DriveInfo([System.IO.Path]::GetPathRoot($root))
        if ($drive.AvailableFreeSpace -lt 5GB) { throw 'Phase 0 preflight requires at least 5GB free disk space' }
        $null = Test-Phase0Package -PackageRoot $root
        $outputPath = Resolve-Phase0ContainedPath -Root $root -RelativePath "$($attempt.relative)/preflight.json"
        $output = [pscustomobject][ordered]@{
            campaign_id = $CampaignId; utc = [DateTime]::UtcNow.ToString('o'); windows_caption = [string]$operatingSystem.Caption
            windows_version = [string]$operatingSystem.Version; operating_system_64 = [Environment]::Is64BitOperatingSystem
            powershell_version = $PSVersionTable.PSVersion.ToString(); administrator = $true
            free_disk_bytes = [int64]$drive.AvailableFreeSpace; package_integrity = 'passed'
        }
        Write-AtomicUtf8Json -PackageRoot $root -FinalPath $outputPath -Value $output
        $relative = ConvertTo-Phase0RelativePath -Root $root -Path $outputPath
        $null = Set-Phase0State -PackageRoot $root -CampaignId $CampaignId -NewState 'PREFLIGHT_PASSED' -Attempt $attempt.number -EvidenceRelativePath $relative
        return $output
    }
    finally { Exit-Phase0CampaignLock -Lock $lock }
}

function Assert-Phase0OwnedTreeNoReparse {
    param([string]$PackageRoot, [string]$Path)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $Path -Expected 'Directory'
    foreach ($item in Get-ChildItem -LiteralPath $Path -Recurse -Force) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Owned runtime tree contains a reparse point: $($item.FullName)"
        }
    }
}

function Remove-Phase0OwnedDirectory {
    param([string]$PackageRoot, [string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Assert-Phase0OwnedTreeNoReparse -PackageRoot $PackageRoot -Path $Path
    [System.IO.Directory]::Delete($Path, $true)
}

function Invoke-Phase0Prepare {
    param([string]$PackageRoot, [string]$CampaignId, [int]$Attempt = 0)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $lock = Enter-Phase0CampaignLock -PackageRoot $root -CampaignId $CampaignId
    $published = $false
    $UmiRoot = $null
    try {
        $null = Assert-Phase0CanTransition -PackageRoot $root -CampaignId $CampaignId -NewState 'PREPARED'
        $attempt = Get-Phase0ActionAttempt -PackageRoot $root -CampaignId $CampaignId -Attempt $Attempt
        $lockValue = Get-Phase0SupplyLock -PackageRoot $root
        $expectedLayout = [ordered]@{
            archive_root = 'Umi-OCR_Rapid_v2.1.5'; data_root = 'Umi-OCR_Rapid_v2.1.5/UmiOCR-data'
            runtime_python = 'Umi-OCR_Rapid_v2.1.5/UmiOCR-data/runtime/python.exe'
            plugin_root = 'Umi-OCR_Rapid_v2.1.5/UmiOCR-data/plugins'; plugin_name = 'win7_x64_RapidOCR-json'
        }
        foreach ($name in $expectedLayout.Keys) {
            if ([string]$lockValue.umi_layout.$name -ne [string]$expectedLayout[$name]) { throw "Unexpected Umi-OCR layout in supply lock: $name" }
        }
        if ([string]$lockValue.umi.name -ne 'Umi-OCR_Rapid_v2.1.5.7z.exe' -or [int64]$lockValue.umi.size -ne 103369422 -or
            [string]$lockValue.umi.sha256 -ne '659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722') {
            throw 'Unexpected official Umi-OCR asset lock'
        }
        $UmiAsset = Resolve-Phase0ContainedPath -Root $root -RelativePath ('vendor/' + [string]$lockValue.umi.name)
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $UmiAsset -Expected 'File'
        $asset = Get-Item -LiteralPath $UmiAsset
        if ($asset.Length -ne [int64]$lockValue.umi.size) { throw 'Official Umi-OCR asset size mismatch' }
        $assetDigest = (Get-FileHash -LiteralPath $UmiAsset -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($assetDigest -ne [string]$lockValue.umi.sha256) { throw 'Official Umi-OCR asset SHA-256 mismatch' }

        $campaignRelative = Get-Phase0CampaignRelativePath $CampaignId
        $finalUmi = Resolve-Phase0ContainedPath -Root $root -RelativePath "$campaignRelative/umi"
        if (Test-Path -LiteralPath $finalUmi) {
            $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $finalUmi -Expected 'Directory'
            $orphan = Resolve-Phase0ContainedPath -Root $root -RelativePath "$($attempt.relative)/orphaned-umi"
            if (Test-Path -LiteralPath $orphan) { throw 'Refusing to overwrite orphaned-umi recovery evidence' }
            $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $orphan -Expected 'Missing'
            [System.IO.Directory]::Move($finalUmi, $orphan)
        }
        $UmiRoot = Ensure-Phase0SafeDirectory -PackageRoot $root -RelativePath "$($attempt.relative)/umi-staging"
        & $UmiAsset -y "-o$UmiRoot"
        if ($LASTEXITCODE -ne 0) { throw "Official Umi-OCR extraction failed: $LASTEXITCODE" }
        Assert-Phase0OwnedTreeNoReparse -PackageRoot $root -Path $UmiRoot
        $runtimePython = Resolve-Phase0ContainedPath -Root $UmiRoot -RelativePath $expectedLayout.runtime_python
        $pluginRoot = Resolve-Phase0ContainedPath -Root $UmiRoot -RelativePath $expectedLayout.plugin_root
        $plugin = Resolve-Phase0ContainedPath -Root $pluginRoot -RelativePath $expectedLayout.plugin_name
        if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf) -or -not (Test-Path -LiteralPath $pluginRoot -PathType Container) -or
            -not (Test-Path -LiteralPath $plugin -PathType Container)) { throw 'Extracted Umi-OCR Rapid package does not match the locked layout' }

        Assert-Phase0OwnedTreeNoReparse -PackageRoot $root -Path $UmiRoot
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path (Get-Phase0CampaignRoot $root $CampaignId) -Expected 'Directory'
        if (Test-Path -LiteralPath $finalUmi) { throw 'Campaign Umi publish target already exists' }
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $finalUmi -Expected 'Missing'
        [System.IO.Directory]::Move($UmiRoot, $finalUmi)
        $published = $true
        $UmiRoot = $null
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $finalUmi -Expected 'Directory'
        $runtimePython = Resolve-Phase0ContainedPath -Root $finalUmi -RelativePath $expectedLayout.runtime_python
        $plugin = Resolve-Phase0ContainedPath -Root $finalUmi -RelativePath ($expectedLayout.plugin_root + '/' + $expectedLayout.plugin_name)
        $outputPath = Resolve-Phase0ContainedPath -Root $root -RelativePath "$($attempt.relative)/run-context.json"
        $output = [pscustomobject][ordered]@{
            campaign_id = $CampaignId; utc = [DateTime]::UtcNow.ToString('o'); umi_asset_sha256 = $assetDigest
            umi_root_relative = ConvertTo-Phase0RelativePath -Root $root -Path $finalUmi
            umi_runtime_relative = ConvertTo-Phase0RelativePath -Root $root -Path $runtimePython
            umi_plugin_relative = ConvertTo-Phase0RelativePath -Root $root -Path $plugin
        }
        Write-AtomicUtf8Json -PackageRoot $root -FinalPath $outputPath -Value $output
        $relative = ConvertTo-Phase0RelativePath -Root $root -Path $outputPath
        $null = Set-Phase0State -PackageRoot $root -CampaignId $CampaignId -NewState 'PREPARED' -Attempt $attempt.number -EvidenceRelativePath $relative
        return $output
    }
    catch {
        if ($published) {
            $finalUmi = Resolve-Phase0ContainedPath -Root $root -RelativePath "$(Get-Phase0CampaignRelativePath $CampaignId)/umi"
            if (Test-Path -LiteralPath $finalUmi) {
                Assert-Phase0OwnedTreeNoReparse -PackageRoot $root -Path $finalUmi
                $failedPublished = Resolve-Phase0ContainedPath -Root $root -RelativePath "$($attempt.relative)/failed-published-umi"
                if (Test-Path -LiteralPath $failedPublished) { throw 'Refusing to overwrite failed-published-umi evidence' }
                $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $failedPublished -Expected 'Missing'
                [System.IO.Directory]::Move($finalUmi, $failedPublished)
            }
        }
        if ($null -ne $UmiRoot -and (Test-Path -LiteralPath $UmiRoot)) {
            Remove-Phase0OwnedDirectory -PackageRoot $root -Path $UmiRoot
        }
        throw
    }
    finally { Exit-Phase0CampaignLock -Lock $lock }
}

function Invoke-Phase0SelfTest {
    param([string]$PackageRoot, [string]$CampaignId, [int]$Attempt = 0)
    $root = Get-Phase0CanonicalRoot -PackageRoot $PackageRoot
    $lock = Enter-Phase0CampaignLock -PackageRoot $root -CampaignId $CampaignId
    try {
        $null = Assert-Phase0CanTransition -PackageRoot $root -CampaignId $CampaignId -NewState 'SELF_TEST_PASSED'
        $attempt = Get-Phase0ActionAttempt -PackageRoot $root -CampaignId $CampaignId -Attempt $Attempt
        $portablePython = Resolve-Phase0ContainedPath -Root $root -RelativePath 'runtime/python/python.exe'
        $toolkitTests = Resolve-Phase0ContainedPath -Root $root -RelativePath 'toolkit/tests'
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $portablePython -Expected 'File'
        $null = Assert-Phase0RuntimeLeaf -PackageRoot $root -Path $toolkitTests -Expected 'Directory'
        & "$root\runtime\python\python.exe" -m pytest "$root\toolkit\tests" -q
        if ($LASTEXITCODE -ne 0) { throw "Portable self-test failed: $LASTEXITCODE" }
        $outputPath = Resolve-Phase0ContainedPath -Root $root -RelativePath "$($attempt.relative)/self-test.json"
        $output = [pscustomobject][ordered]@{ campaign_id = $CampaignId; utc = [DateTime]::UtcNow.ToString('o'); result = 'passed'; exit_code = 0 }
        Write-AtomicUtf8Json -PackageRoot $root -FinalPath $outputPath -Value $output
        $relative = ConvertTo-Phase0RelativePath -Root $root -Path $outputPath
        $null = Set-Phase0State -PackageRoot $root -CampaignId $CampaignId -NewState 'SELF_TEST_PASSED' -Attempt $attempt.number -EvidenceRelativePath $relative
        return $output
    }
    finally { Exit-Phase0CampaignLock -Lock $lock }
}

Export-ModuleMember -Function @(
    'Test-Phase0Package', 'Invoke-Phase0Preflight', 'Invoke-Phase0Prepare', 'Invoke-Phase0SelfTest',
    'Get-Phase0State', 'Set-Phase0State', 'Write-Phase0Failure', 'Enter-Phase0CampaignLock',
    'Exit-Phase0CampaignLock', 'Get-Phase0AttemptContext'
)
