Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$packageModule = Join-Path $PSScriptRoot 'Phase0.Package.psm1'
Import-Module $packageModule -Force

function Assert-Phase0SchedulerIdentifier {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Name)
    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
        throw "$Name must contain only safe identifier characters and be at most 128 characters"
    }
}

function Get-Phase0SchedulerRoot {
    param([Parameter(Mandatory = $true)][string]$PackageRoot)
    if ($PackageRoot -match '[\x00-\x1F\x7F]') { throw 'Package path contains control characters' }
    return [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $PackageRoot).Path).TrimEnd('\', '/')
}

function Resolve-Phase0SchedulerPath {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [switch]$AllowMissing
    )
    if ([string]::IsNullOrWhiteSpace($RelativePath) -or [System.IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath -match '[\x00-\x1F\x7F]') {
        throw "Unsafe relative path: $RelativePath"
    }
    $segments = $RelativePath -split '[\\/]'
    if ($segments -contains '' -or $segments -contains '.' -or $segments -contains '..') {
        throw "Unsafe relative path: $RelativePath"
    }
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $root ($RelativePath -replace '/', '\')))
    if (-not $candidate.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes package root: $RelativePath"
    }
    $current = $candidate
    while (-not $current.Equals($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Runtime path contains a reparse point: $current"
            }
        }
        $current = [System.IO.Path]::GetDirectoryName($current).TrimEnd('\', '/')
    }
    if (-not $AllowMissing -and -not (Test-Path -LiteralPath $candidate)) {
        throw "Required runtime path is missing: $RelativePath"
    }
    return $candidate
}

function ConvertTo-Phase0SchedulerRelativePath {
    param([string]$PackageRoot, [string]$Path)
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $candidate = [System.IO.Path]::GetFullPath($Path)
    $prefix = $root + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Runtime evidence path is outside the package root'
    }
    return $candidate.Substring($prefix.Length).Replace('\', '/')
}

function Write-Phase0SchedulerJson {
    param([string]$PackageRoot, [string]$Path, $Value)
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $Path
    $target = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $relative -AllowMissing
    $parent = [System.IO.Path]::GetDirectoryName($target)
    $parentRelative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $parent
    $null = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $parentRelative
    if (Test-Path -LiteralPath $target) { throw "Refusing to overwrite runtime evidence: $relative" }
    $temporary = "$target.$([guid]::NewGuid().ToString('N')).tmp"
    $stream = $null
    $writer = $null
    try {
        $stream = New-Object System.IO.FileStream(
            $temporary, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None
        )
        $writer = New-Object System.IO.StreamWriter($stream, (New-Object System.Text.UTF8Encoding($false)))
        $writer.Write(($Value | ConvertTo-Json -Depth 20) + [Environment]::NewLine)
        $writer.Flush()
        $stream.Flush($true)
        $writer.Dispose()
        $writer = $null
        $stream = $null
        $null = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $parentRelative
        if (Test-Path -LiteralPath $target) { throw "Refusing to overwrite runtime evidence: $relative" }
        [System.IO.File]::Move($temporary, $target)
    }
    finally {
        if ($null -ne $writer) { $writer.Dispose(); $stream = $null }
        if ($null -ne $stream) { $stream.Dispose() }
        if (Test-Path -LiteralPath $temporary) { [System.IO.File]::Delete($temporary) }
    }
    return $target
}

function Get-Phase0RunContext {
    param([string]$PackageRoot, [string]$CampaignId)
    Assert-Phase0SchedulerIdentifier -Value $CampaignId -Name 'CampaignId'
    $attempts = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath "work/campaigns/$CampaignId/attempts"
    $contexts = @()
    foreach ($directory in Get-ChildItem -LiteralPath $attempts -Force | Sort-Object Name -Descending) {
        if (-not $directory.PSIsContainer -or $directory.Name -notmatch '^attempt-[0-9]{4,10}$' -or
            ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Unexpected entry in attempts directory: $($directory.Name)"
        }
        $candidate = Join-Path $directory.FullName 'run-context.json'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $candidateRelative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $candidate
            $contexts += Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath $candidateRelative
        }
    }
    if ($contexts.Count -lt 1) { throw 'Prepared run-context.json is missing' }
    $context = [System.IO.File]::ReadAllText($contexts[0], [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    $expected = @('campaign_id', 'utc', 'umi_asset_sha256', 'umi_root_relative', 'umi_runtime_relative', 'umi_plugin_relative') | Sort-Object
    $actual = @($context.PSObject.Properties.Name | Sort-Object)
    if (@(Compare-Object $expected $actual).Count -ne 0 -or $context.campaign_id -ne $CampaignId) {
        throw 'Prepared run context is invalid'
    }
    foreach ($name in @('umi_root_relative', 'umi_runtime_relative', 'umi_plugin_relative')) {
        $null = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath ([string]$context.$name)
    }
    return $context
}

function Get-Phase0RunnerConfiguration {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId, [ValidateSet('Interactive', 'Scheduled')][string]$ExecutionMode, $Attempt)
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $context = Get-Phase0RunContext -PackageRoot $root -CampaignId $CampaignId
    $runtimePython = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath ([string]$context.umi_runtime_relative)
    $plugin = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath ([string]$context.umi_plugin_relative)
    $pluginRoot = [System.IO.Path]::GetDirectoryName($plugin)
    $umiDataRoot = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetDirectoryName($runtimePython))
    $projectRoot = if (Test-Path -LiteralPath (Join-Path $root 'toolkit/src') -PathType Container) { Join-Path $root 'toolkit' } else { $root }
    $runner = if (Test-Path -LiteralPath (Join-Path $root 'toolkit/scripts/run-windows-validation.ps1') -PathType Leaf) {
        Join-Path $root 'toolkit/scripts/run-windows-validation.ps1'
    } else { Join-Path $root 'scripts/run-windows-validation.ps1' }
    foreach ($path in @($runner, (Join-Path $root 'runtime/python/python.exe'), (Join-Path $root 'templates/global-options.json'),
        (Join-Path $root 'templates/local-options.json'), (Join-Path $root 'templates/samples.json'))) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required validation input is missing: $path" }
    }
    $mode = $ExecutionMode.ToLowerInvariant()
    $output = Join-Path $Attempt.root "ocr/$mode/$ValidationId"
    return [pscustomobject][ordered]@{
        project_root = $projectRoot
        umi_data_root = $umiDataRoot
        test_python_exe = Join-Path $root 'runtime/python/python.exe'
        python_exe = $runtimePython
        plugin_root = $pluginRoot
        plugin_name = [System.IO.Path]::GetFileName($plugin)
        global_options = Join-Path $root 'templates/global-options.json'
        local_options = Join-Path $root 'templates/local-options.json'
        samples_manifest = Join-Path $root 'templates/samples.json'
        validation_id = $ValidationId
        campaign_id = $CampaignId
        execution_mode = $ExecutionMode
        output_dir = $output
        min_pages = 100
        business_concurrency_limit = 5
        stdout_log = Join-Path $Attempt.root "$mode-stdout.log"
        stderr_log = Join-Path $Attempt.root "$mode-stderr.log"
        runner = $runner
    }
}

function Invoke-Phase0Runner {
    param([string]$PackageRoot, $Configuration, $Attempt)
    $argumentValues = [ordered]@{}
    foreach ($property in $Configuration.PSObject.Properties) {
        if ($property.Name -ne 'runner') { $argumentValues[$property.Name] = $property.Value }
    }
    $argumentFile = Join-Path $Attempt.root 'interactive-arguments.json'
    $null = Write-Phase0SchedulerJson -PackageRoot $PackageRoot -Path $argumentFile -Value $argumentValues
    $powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powerShell -PathType Leaf)) { throw 'Windows PowerShell executable is missing' }
    & $powerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Configuration.runner -ArgumentFile $argumentFile
    return [int]$LASTEXITCODE
}

function New-Phase0PublishedFailure {
    param([string]$Message)
    $exception = New-Object System.InvalidOperationException($Message)
    $exception.Data['Phase0StatePublished'] = $true
    return $exception
}

function Invoke-InteractiveValidation {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId, [Parameter(Mandatory = $true)]$Attempt)
    Assert-Phase0SchedulerIdentifier -Value $ValidationId -Name 'ValidationId'
    $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
    if ($state.state -ne 'SELF_TEST_PASSED') { throw 'Interactive validation requires SELF_TEST_PASSED' }
    $configuration = Get-Phase0RunnerConfiguration -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -ExecutionMode Interactive -Attempt $Attempt
    $exitCode = Invoke-Phase0Runner -PackageRoot $PackageRoot -Configuration $configuration -Attempt $Attempt
    $manifest = Join-Path $configuration.output_dir 'manifest.json'
    $manifestValid = $false
    if (Test-Path -LiteralPath $manifest -PathType Leaf) {
        $manifestRelative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $manifest
        $manifest = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath $manifestRelative
        $manifestValue = [System.IO.File]::ReadAllText($manifest, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        $manifestValid = $manifestValue.campaign_id -eq $CampaignId -and $manifestValue.validation_id -eq $ValidationId -and
            $manifestValue.execution_mode -eq 'interactive' -and $manifestValue.status -eq 'completed' -and
            $manifestValue.passed -eq $true
    }
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
        $manifest = Write-Phase0SchedulerJson -PackageRoot $PackageRoot -Path (Join-Path $Attempt.root 'interactive-run.json') -Value ([ordered]@{
            campaign_id = $CampaignId; validation_id = $ValidationId; execution_mode = 'interactive'; exit_code = $exitCode
            recorded_at_utc = [DateTime]::UtcNow.ToString('o'); result = 'failed_without_manifest'
        })
    }
    $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $manifest
    $interactivePassed = $exitCode -eq 0 -and $manifestValid
    $nextState = if ($interactivePassed) { 'INTERACTIVE_OCR_PASSED' } else { 'INTERACTIVE_OCR_FAILED' }
    $null = Set-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId -NewState $nextState -Attempt $Attempt.number `
        -EvidenceRelativePath $relative -ValidationKind Interactive -ValidationId $ValidationId
    if (-not $interactivePassed) { throw (New-Phase0PublishedFailure -Message "Interactive OCR validation failed: $exitCode") }
    return [pscustomobject]@{ validation_id = $ValidationId; output_dir = $configuration.output_dir; exit_code = 0 }
}

function New-Phase0TaskDefinition {
    param(
        [Parameter(Mandatory = $true)][string]$ValidationId,
        [Parameter(Mandatory = $true)][string]$CommandPath,
        [Parameter(Mandatory = $true)][string]$RunnerPath,
        [Parameter(Mandatory = $true)][string]$ArgumentFile,
        [string]$UserName = '<credential-required>'
    )
    Assert-Phase0SchedulerIdentifier -Value $ValidationId -Name 'ValidationId'
    $TaskName = "UmiOcrPhase0-$ValidationId"
    return [pscustomobject][ordered]@{
        task_name = $TaskName
        execute = $CommandPath
        arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$RunnerPath`" -ArgumentFile `"$ArgumentFile`""
        argument_file = $ArgumentFile
        logon_type = 'Password'
        run_level = 'Highest'
        execution_time_limit = 'PT6H'
        start_when_available = $true
        user_name = $UserName
    }
}

function Write-Phase0RestrictedArgumentFile {
    param([string]$Path, $Value, [string]$UserName)
    if (Test-Path -LiteralPath $Path) { throw 'Refusing to overwrite scheduled-task argument file' }
    $userSid = (New-Object System.Security.Principal.NTAccount($UserName)).Translate([System.Security.Principal.SecurityIdentifier])
    $systemSid = New-Object System.Security.Principal.SecurityIdentifier([System.Security.Principal.WellKnownSidType]::LocalSystemSid, $null)
    $administratorsSid = New-Object System.Security.Principal.SecurityIdentifier([System.Security.Principal.WellKnownSidType]::BuiltinAdministratorsSid, $null)
    $security = New-Object System.Security.AccessControl.FileSecurity
    $security.SetAccessRuleProtection($true, $false)
    foreach ($entry in @(
        [pscustomobject]@{ Sid = $systemSid; Rights = [System.Security.AccessControl.FileSystemRights]::FullControl },
        [pscustomobject]@{ Sid = $administratorsSid; Rights = [System.Security.AccessControl.FileSystemRights]::FullControl },
        [pscustomobject]@{ Sid = $userSid; Rights = [System.Security.AccessControl.FileSystemRights]::Read }
    )) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $entry.Sid, $entry.Rights, [System.Security.AccessControl.AccessControlType]::Allow
        )
        $null = $security.AddAccessRule($rule)
    }
    $stream = New-Object System.IO.FileStream(
        $Path, [System.IO.FileMode]::CreateNew, [System.Security.AccessControl.FileSystemRights]::Write,
        [System.IO.FileShare]::None, 4096, [System.IO.FileOptions]::WriteThrough, $security
    )
    $writer = $null
    try {
        $writer = New-Object System.IO.StreamWriter($stream, (New-Object System.Text.UTF8Encoding($false)))
        $writer.Write(($Value | ConvertTo-Json -Depth 10) + [Environment]::NewLine)
        $writer.Flush()
        $stream.Flush($true)
    }
    finally {
        if ($null -ne $writer) { $writer.Dispose() } else { $stream.Dispose() }
    }
}

function Install-Phase0ScheduledTask {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$CampaignId,
        [Parameter(Mandatory = $true)][string]$ValidationId,
        [Parameter(Mandatory = $true)]$Attempt,
        [string]$CommandPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe",
        [string]$ArgumentFile = '',
        [System.Management.Automation.PSCredential]$Credential,
        [switch]$DryRun
    )
    Assert-Phase0SchedulerIdentifier -Value $ValidationId -Name 'ValidationId'
    $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
    if ($state.state -ne 'INTERACTIVE_OCR_PASSED') { throw 'Scheduled validation requires INTERACTIVE_OCR_PASSED' }
    if ($null -ne $state.interactive_validation_id -and $state.interactive_validation_id -eq $ValidationId) {
        throw 'Interactive and scheduled validation IDs must be different'
    }
    $expectedPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $canonicalCommand = [System.IO.Path]::GetFullPath($CommandPath)
    $canonicalPowerShell = [System.IO.Path]::GetFullPath($expectedPowerShell)
    if (-not $canonicalCommand.Equals($canonicalPowerShell, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Scheduled task must use the system Windows PowerShell executable'
    }
    $configuration = Get-Phase0RunnerConfiguration -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -ExecutionMode Scheduled -Attempt $Attempt
    if ([string]::IsNullOrWhiteSpace($ArgumentFile)) { $ArgumentFile = Join-Path $Attempt.root 'scheduled-arguments.json' }
    $argumentRelative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $ArgumentFile
    $ArgumentFile = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath $argumentRelative -AllowMissing
    $argumentParent = [System.IO.Path]::GetDirectoryName($ArgumentFile)
    $null = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot `
        -RelativePath (ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $argumentParent)
    $definition = New-Phase0TaskDefinition -ValidationId $ValidationId -CommandPath $CommandPath -RunnerPath $configuration.runner -ArgumentFile $ArgumentFile
    if ($DryRun) { return $definition }
    $TaskName = "UmiOcrPhase0-$ValidationId"
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw "Scheduled task already exists: $TaskName" }
    if ($null -eq $Credential) { $Credential = Get-Credential -Message 'Phase 0 scheduled-task account' }
    $userName = $Credential.UserName
    $arguments = [ordered]@{}
    foreach ($property in $configuration.PSObject.Properties) {
        if ($property.Name -ne 'runner') { $arguments[$property.Name] = $property.Value }
    }
    Write-Phase0RestrictedArgumentFile -Path $ArgumentFile -Value $arguments -UserName $userName
    $definition = New-Phase0TaskDefinition -ValidationId $ValidationId -CommandPath $CommandPath -RunnerPath $configuration.runner -ArgumentFile $ArgumentFile -UserName $userName

    $TaskAction = New-ScheduledTaskAction -Execute $definition.execute -Argument $definition.arguments
    $TaskSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 6) -StartWhenAvailable
    $TaskPrincipal = New-ScheduledTaskPrincipal -UserId $userName -LogonType Password -RunLevel Highest
    $TaskDefinition = New-ScheduledTask -Action $TaskAction -Settings $TaskSettings -Principal $TaskPrincipal
    $PlainPassword = $Credential.GetNetworkCredential().Password
    try {
        Register-ScheduledTask -TaskName $TaskName -InputObject $TaskDefinition -User $userName -Password $PlainPassword | Out-Null
    }
    finally {
        $PlainPassword = $null
        $Credential = $null
    }
    $metadataPath = Join-Path $Attempt.root 'scheduled-task.json'
    $metadata = [ordered]@{
        campaign_id = $CampaignId; validation_id = $ValidationId; attempt = $Attempt.number; task_name = $TaskName
        installed_at_utc = [DateTime]::UtcNow.ToString('o')
        argument_file_relative = $argumentRelative
        output_dir_relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $configuration.output_dir
        stdout_log_relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $configuration.stdout_log
        stderr_log_relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $configuration.stderr_log
    }
    $null = Write-Phase0SchedulerJson -PackageRoot $PackageRoot -Path $metadataPath -Value $metadata
    Start-ScheduledTask -TaskName $TaskName
    return $definition
}

function Get-Phase0ExistingSchedule {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId)
    $attempts = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath "work/campaigns/$CampaignId/attempts"
    $records = @()
    foreach ($directory in Get-ChildItem -LiteralPath $attempts -Force) {
        if (-not $directory.PSIsContainer -or $directory.Name -notmatch '^attempt-[0-9]{4,10}$' -or
            ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Unexpected entry in attempts directory: $($directory.Name)"
        }
        $candidate = Get-Item -LiteralPath (Join-Path $directory.FullName 'scheduled-task.json') -ErrorAction SilentlyContinue
        if ($null -eq $candidate) { continue }
        if ($candidate.PSIsContainer -or ($candidate.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Scheduled-task record must be a normal file'
        }
        $value = [System.IO.File]::ReadAllText($candidate.FullName, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        $expectedProperties = @(
            'argument_file_relative', 'attempt', 'campaign_id', 'installed_at_utc', 'output_dir_relative',
            'stderr_log_relative', 'stdout_log_relative', 'task_name', 'validation_id'
        ) | Sort-Object
        $actualProperties = @($value.PSObject.Properties.Name | Sort-Object)
        if (@(Compare-Object $expectedProperties $actualProperties).Count -ne 0) {
            throw 'Scheduled-task record contains unexpected or missing fields'
        }
        $attemptNumber = 0
        if (-not [int]::TryParse([string]$value.attempt, [ref]$attemptNumber) -or $attemptNumber -lt 1 -or
            $directory.Name -ne ('attempt-{0:D4}' -f $attemptNumber)) {
            throw 'Scheduled-task record attempt is invalid'
        }
        $expectedPrefix = "work/campaigns/$CampaignId/attempts/$($directory.Name)/"
        $expectedOutput = "$expectedPrefix" + "ocr/scheduled/$ValidationId"
        if (-not ([string]$value.argument_file_relative).StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
            [string]$value.output_dir_relative -ne $expectedOutput -or
            [string]$value.stdout_log_relative -ne ($expectedPrefix + 'scheduled-stdout.log') -or
            [string]$value.stderr_log_relative -ne ($expectedPrefix + 'scheduled-stderr.log')) {
            throw 'Scheduled-task record paths are not bound to its attempt'
        }
        if ($value.campaign_id -eq $CampaignId -and $value.validation_id -eq $ValidationId) { $records += ,@($candidate, $value) }
    }
    if ($records.Count -ne 1) { throw 'Expected exactly one installed scheduled-task record' }
    $metadata = $records[0][1]
    $attemptRoot = [System.IO.Path]::GetDirectoryName($records[0][0].FullName)
    return [pscustomobject]@{ metadata = $metadata; attempt = [pscustomobject]@{ number = [int]$metadata.attempt; root = $attemptRoot } }
}

function Get-Phase0LogSummary {
    param([string]$PackageRoot, [string]$RelativePath)
    $path = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath $RelativePath -AllowMissing
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return [pscustomobject][ordered]@{ path = $RelativePath; exists = $false; length = 0; sha256 = $null }
    }
    $item = Get-Item -LiteralPath $path
    return [pscustomobject][ordered]@{
        path = $RelativePath; exists = $true; length = [int64]$item.Length
        sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-Phase0TextSha256 {
    param([string]$Text)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try { $digest = $algorithm.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text)) }
    finally { $algorithm.Dispose() }
    return (($digest | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Collect-Phase0ScheduledTask {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId)
    Assert-Phase0SchedulerIdentifier -Value $ValidationId -Name 'ValidationId'
    $schedule = Get-Phase0ExistingSchedule -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId
    $TaskName = "UmiOcrPhase0-$ValidationId"
    if ($schedule.metadata.task_name -ne $TaskName) { throw 'Scheduled-task record name mismatch' }
    $startedAtUtc = [string]$schedule.metadata.installed_at_utc
    $installedAt = [DateTime]::MinValue
    if (-not [DateTime]::TryParse($startedAtUtc, [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind, [ref]$installedAt) -or $installedAt.Kind -ne [DateTimeKind]::Utc) {
        throw 'Scheduled-task install timestamp is invalid'
    }
    $deadline = $installedAt.Add((New-TimeSpan -Hours 6))
    do {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
        $hasStarted = $taskInfo.LastRunTime -gt [DateTime]'1601-01-02T00:00:00Z'
        if ([string]$task.State -notin @('Running', 'Queued') -and $hasStarted) { break }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'Scheduled OCR collection timed out after 6 hours' }
        Start-Sleep -Seconds 5
    } while ($true)
    $taskXml = Export-ScheduledTask -TaskName $TaskName
    $outputDir = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath ([string]$schedule.metadata.output_dir_relative) -AllowMissing
    $resourcesPath = Join-Path $outputDir 'resources.json'
    $manifestPath = Join-Path $outputDir 'manifest.json'
    $windowsSessionId = $null
    $manifestStatus = 'missing'
    $manifestPassed = $false
    $resourcesBindingValid = $false
    $manifestBindingValid = $false
    if (Test-Path -LiteralPath $resourcesPath -PathType Leaf) {
        $resourcesRelative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $resourcesPath
        $resourcesPath = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath $resourcesRelative
        $resources = [System.IO.File]::ReadAllText($resourcesPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        $windowsSessionId = $resources.details.windows_session_id
        $resourcesBindingValid = $resources.campaign_id -eq $CampaignId -and $resources.validation_id -eq $ValidationId -and
            $resources.execution_mode -eq 'scheduled'
    }
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        $manifestRelative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $manifestPath
        $manifestPath = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath $manifestRelative
        $manifest = [System.IO.File]::ReadAllText($manifestPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        $manifestStatus = [string]$manifest.status
        $manifestPassed = $manifest.passed -eq $true
        $manifestBindingValid = $manifest.campaign_id -eq $CampaignId -and $manifest.validation_id -eq $ValidationId -and
            $manifest.execution_mode -eq 'scheduled'
    }
    $lastTaskResult = [int64]$taskInfo.LastTaskResult
    $definitionValid = $false
    try {
        [xml]$taskDocument = $taskXml
        $logonType = $taskDocument.SelectSingleNode("//*[local-name()='LogonType']").InnerText
        $runLevel = $taskDocument.SelectSingleNode("//*[local-name()='RunLevel']").InnerText
        $executionLimitText = $taskDocument.SelectSingleNode("//*[local-name()='ExecutionTimeLimit']").InnerText
        $executionLimit = [System.Xml.XmlConvert]::ToTimeSpan($executionLimitText)
        $taskCommand = $taskDocument.SelectSingleNode("//*[local-name()='Exec']/*[local-name()='Command']").InnerText
        $taskArguments = $taskDocument.SelectSingleNode("//*[local-name()='Exec']/*[local-name()='Arguments']").InnerText
        $expectedPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $expectedRunner = if (Test-Path -LiteralPath (Join-Path (Get-Phase0SchedulerRoot $PackageRoot) 'toolkit/scripts/run-windows-validation.ps1')) {
            Join-Path (Get-Phase0SchedulerRoot $PackageRoot) 'toolkit/scripts/run-windows-validation.ps1'
        } else { Join-Path (Get-Phase0SchedulerRoot $PackageRoot) 'scripts/run-windows-validation.ps1' }
        $argumentFile = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath ([string]$schedule.metadata.argument_file_relative)
        $expectedDefinition = New-Phase0TaskDefinition -ValidationId $ValidationId -CommandPath $expectedPowerShell `
            -RunnerPath $expectedRunner -ArgumentFile $argumentFile
        $canonicalTaskCommand = [System.IO.Path]::GetFullPath($taskCommand)
        $canonicalPowerShell = [System.IO.Path]::GetFullPath($expectedPowerShell)
        $definitionValid = $logonType -eq 'Password' -and $runLevel -eq 'HighestAvailable' -and
            $executionLimit -eq (New-TimeSpan -Hours 6) -and
            $canonicalTaskCommand.Equals($canonicalPowerShell, [System.StringComparison]::OrdinalIgnoreCase) -and
            $taskArguments -eq $expectedDefinition.arguments
    }
    catch { $definitionValid = $false }
    $passed = $lastTaskResult -eq 0 -and $manifestStatus -eq 'completed' -and $manifestPassed -and $null -ne $windowsSessionId -and
        [int64]$windowsSessionId -eq 0 -and $resourcesBindingValid -and $manifestBindingValid -and $definitionValid
    $summary = [ordered]@{
        campaign_id = $CampaignId; validation_id = $ValidationId; task_name = $TaskName
        installed_at_utc = $startedAtUtc; started_at_utc = $taskInfo.LastRunTime.ToUniversalTime().ToString('o')
        ended_at_utc = [DateTime]::UtcNow.ToString('o')
        LastTaskResult = $lastTaskResult; windows_session_id = $windowsSessionId
        task_xml_sha256 = Get-Phase0TextSha256 -Text $taskXml; task_definition_valid = $definitionValid
        resources_binding_valid = $resourcesBindingValid; manifest_binding_valid = $manifestBindingValid
        manifest_status = $manifestStatus; manifest_passed = $manifestPassed
        log_summaries = @(
            Get-Phase0LogSummary -PackageRoot $PackageRoot -RelativePath ([string]$schedule.metadata.stdout_log_relative)
            Get-Phase0LogSummary -PackageRoot $PackageRoot -RelativePath ([string]$schedule.metadata.stderr_log_relative)
        )
        result = if ($passed) { 'passed' } else { 'failed' }
    }
    $summaryPath = Write-Phase0SchedulerJson -PackageRoot $PackageRoot -Path (Join-Path $schedule.attempt.root 'scheduled-collection.json') -Value $summary
    $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $summaryPath
    $nextState = if ($passed) { 'SCHEDULED_OCR_PASSED' } else { 'SCHEDULED_OCR_FAILED' }
    $null = Set-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId -NewState $nextState -Attempt $schedule.attempt.number `
        -EvidenceRelativePath $relative -ValidationKind Scheduled -ValidationId $ValidationId
    if (-not $passed) { throw (New-Phase0PublishedFailure -Message "Scheduled OCR validation failed: $lastTaskResult") }
    return [pscustomobject]$summary
}

function Remove-Phase0ScheduledTask {
    param([string]$ValidationId, [switch]$ConfirmCleanup)
    if (-not $ConfirmCleanup) { throw 'ConfirmCleanup is required' }
    Assert-Phase0SchedulerIdentifier -Value $ValidationId -Name 'ValidationId'
    $TaskName = "UmiOcrPhase0-$ValidationId"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Export-ModuleMember -Function @(
    'Invoke-InteractiveValidation', 'New-Phase0TaskDefinition', 'Install-Phase0ScheduledTask',
    'Collect-Phase0ScheduledTask', 'Remove-Phase0ScheduledTask'
)
