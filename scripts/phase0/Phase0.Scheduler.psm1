Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'Phase0.Package.psm1') -Force

function Assert-Phase0SchedulerIdentifier {
    param([string]$Value, [string]$Name)
    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
        throw "$Name must contain only safe identifier characters and be at most 128 characters"
    }
}

function Get-Phase0SchedulerRoot {
    param([string]$PackageRoot)
    if ($PackageRoot -match '[\x00-\x1F\x7F]') { throw 'Package path contains control characters' }
    return [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $PackageRoot).Path).TrimEnd('\', '/')
}

function Resolve-Phase0SchedulerPath {
    param([string]$PackageRoot, [string]$RelativePath, [switch]$AllowMissing)
    if ([string]::IsNullOrWhiteSpace($RelativePath) -or [System.IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath -match '[\x00-\x1F\x7F]') { throw "Unsafe relative path: $RelativePath" }
    $segments = $RelativePath -split '[\\/]'
    if ($segments -contains '' -or $segments -contains '.' -or $segments -contains '..') {
        throw "Unsafe relative path: $RelativePath"
    }
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $root ($RelativePath -replace '/', '\')))
    $prefix = $root + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
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
        $parent = [System.IO.Path]::GetDirectoryName($current)
        if ([string]::IsNullOrEmpty($parent) -or $parent -eq $current) { throw 'Unable to prove path containment' }
        $current = $parent.TrimEnd('\', '/')
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
        throw 'Runtime path is outside the package root'
    }
    return $candidate.Substring($prefix.Length).Replace('\', '/')
}

function Assert-Phase0ExactPath {
    param([string]$Actual, [string]$Expected, [string]$Name)
    $actualFull = [System.IO.Path]::GetFullPath($Actual).TrimEnd('\', '/')
    $expectedFull = [System.IO.Path]::GetFullPath($Expected).TrimEnd('\', '/')
    if (-not $actualFull.Equals($expectedFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Name is outside the trusted package relationship"
    }
}

function Get-Phase0Sha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-Phase0TextSha256 {
    param([string]$Text)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try { $digest = $algorithm.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text)) }
    finally { $algorithm.Dispose() }
    return (($digest | ForEach-Object { $_.ToString('x2') }) -join '')
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
        $writer.Write(($Value | ConvertTo-Json -Depth 30) + [Environment]::NewLine)
        $writer.Flush(); $stream.Flush($true)
        $writer.Dispose(); $writer = $null; $stream = $null
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

function Get-Phase0WellKnownSids {
    $administrators = New-Object System.Security.Principal.SecurityIdentifier(
        [System.Security.Principal.WellKnownSidType]::BuiltinAdministratorsSid, $null
    )
    $system = New-Object System.Security.Principal.SecurityIdentifier(
        [System.Security.Principal.WellKnownSidType]::LocalSystemSid, $null
    )
    return [pscustomobject]@{ administrators = $administrators; system = $system }
}

function New-Phase0ScheduleSecurity {
    param([System.Security.Principal.SecurityIdentifier]$AccountSid, [switch]$Directory)
    $sids = Get-Phase0WellKnownSids
    $security = if ($Directory) {
        New-Object System.Security.AccessControl.DirectorySecurity
    } else { New-Object System.Security.AccessControl.FileSecurity }
    $security.SetAccessRuleProtection($true, $false)
    $security.SetOwner($sids.administrators)
    $inheritance = if ($Directory) {
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else { [System.Security.AccessControl.InheritanceFlags]::None }
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    foreach ($entry in @(
        [pscustomobject]@{ Sid = $sids.system; Rights = [System.Security.AccessControl.FileSystemRights]::FullControl },
        [pscustomobject]@{ Sid = $sids.administrators; Rights = [System.Security.AccessControl.FileSystemRights]::FullControl },
        [pscustomobject]@{ Sid = $AccountSid; Rights = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute }
    )) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $entry.Sid, $entry.Rights, $inheritance, $propagation,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $null = $security.AddAccessRule($rule)
    }
    return $security
}

function ConvertTo-Phase0Sid {
    param($IdentityReference)
    return $IdentityReference.Translate([System.Security.Principal.SecurityIdentifier])
}

function Assert-Phase0RestrictedSchedulePath {
    param([string]$Path, [string]$AccountSid = '', [ValidateSet('Directory', 'File')][string]$Kind)
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        ($Kind -eq 'Directory' -and -not $item.PSIsContainer) -or
        ($Kind -eq 'File' -and $item.PSIsContainer)) { throw 'Restricted schedule path is not a normal expected object' }
    $acl = Get-Acl -LiteralPath $Path
    if (-not $acl.AreAccessRulesProtected) { throw 'Restricted schedule ACL inheritance must be disabled' }
    $sids = Get-Phase0WellKnownSids
    try { $owner = (New-Object System.Security.Principal.NTAccount($acl.Owner)).Translate([System.Security.Principal.SecurityIdentifier]) }
    catch { $owner = New-Object System.Security.Principal.SecurityIdentifier($acl.Owner) }
    if ($owner.Value -notin @($sids.administrators.Value, $sids.system.Value)) {
        throw 'Restricted schedule owner is not trusted'
    }
    $observedAccount = $null
    $seenAdministrators = $false
    $seenSystem = $false
    foreach ($rule in $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])) {
        if ($rule.IsInherited -or $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) {
            throw 'Restricted schedule ACL contains inherited or deny rules'
        }
        $sid = [string]$rule.IdentityReference.Value
        if ($sid -eq $sids.administrators.Value) {
            if (($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -ne
                [System.Security.AccessControl.FileSystemRights]::FullControl) { throw 'Administrators require full control' }
            $seenAdministrators = $true; continue
        }
        if ($sid -eq $sids.system.Value) {
            if (($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -ne
                [System.Security.AccessControl.FileSystemRights]::FullControl) { throw 'SYSTEM requires full control' }
            $seenSystem = $true; continue
        }
        if ($null -ne $observedAccount -and $observedAccount -ne $sid) { throw 'Restricted schedule ACL has extra identities' }
        $mutationMask = [System.Security.AccessControl.FileSystemRights]::WriteData -bor
            [System.Security.AccessControl.FileSystemRights]::CreateFiles -bor
            [System.Security.AccessControl.FileSystemRights]::AppendData -bor
            [System.Security.AccessControl.FileSystemRights]::CreateDirectories -bor
            [System.Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
            [System.Security.AccessControl.FileSystemRights]::WriteAttributes -bor
            [System.Security.AccessControl.FileSystemRights]::Delete -bor
            [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
            [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
            [System.Security.AccessControl.FileSystemRights]::TakeOwnership
        $requiredRead = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
        if (($rule.FileSystemRights -band $mutationMask) -ne 0 -or
            ($rule.FileSystemRights -band $requiredRead) -ne $requiredRead) {
            throw 'Scheduled execution account must be read-only'
        }
        $observedAccount = $sid
    }
    if (-not $seenAdministrators -or -not $seenSystem -or $null -eq $observedAccount) {
        throw 'Restricted schedule ACL is incomplete'
    }
    if (-not [string]::IsNullOrWhiteSpace($AccountSid) -and $observedAccount -ne $AccountSid) {
        throw 'Restricted schedule execution SID mismatch'
    }
    return $observedAccount
}

function New-Phase0RestrictedScheduleDirectory {
    param([string]$PackageRoot, $Attempt, [string]$ValidationId, [System.Security.Principal.SecurityIdentifier]$AccountSid)
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $attemptRelative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $Attempt.root
    $attemptPath = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $attemptRelative
    $attemptSecurity = New-Phase0ScheduleSecurity -AccountSid $AccountSid -Directory
    [System.IO.Directory]::SetAccessControl($attemptPath, $attemptSecurity)
    $null = Assert-Phase0RestrictedSchedulePath -Path $attemptPath -AccountSid $AccountSid.Value -Kind Directory
    $secureRelative = "$attemptRelative/secure"
    $scheduleRelative = "$secureRelative/schedule-$ValidationId"
    foreach ($definition in @(
        [pscustomobject]@{ Relative = $secureRelative; Parent = $attemptRelative },
        [pscustomobject]@{ Relative = $scheduleRelative; Parent = $secureRelative }
    )) {
        $parent = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $definition.Parent
        $path = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $definition.Relative -AllowMissing
        if (Test-Path -LiteralPath $path) { throw 'Restricted schedule directory already exists' }
        $null = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $definition.Parent
        $security = New-Phase0ScheduleSecurity -AccountSid $AccountSid -Directory
        $null = [System.IO.Directory]::CreateDirectory($path, $security)
        $null = Assert-Phase0RestrictedSchedulePath -Path $path -AccountSid $AccountSid.Value -Kind Directory
    }
    $result = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $scheduleRelative
    return $result
}

function Write-Phase0RestrictedJsonAtomic {
    param([string]$PackageRoot, [string]$Directory, [string]$Name, $Value, [System.Security.Principal.SecurityIdentifier]$AccountSid)
    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') { throw 'Restricted file name is unsafe' }
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $directoryRelative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $Directory
    $trustedDirectory = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $directoryRelative
    $null = Assert-Phase0RestrictedSchedulePath -Path $trustedDirectory -AccountSid $AccountSid.Value -Kind Directory
    $target = Join-Path $trustedDirectory $Name
    if (Test-Path -LiteralPath $target) { throw 'Refusing to overwrite restricted schedule file' }
    $temporary = Join-Path $trustedDirectory ('.' + $Name + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    $security = New-Phase0ScheduleSecurity -AccountSid $AccountSid
    $stream = $null; $writer = $null
    try {
        $stream = New-Object System.IO.FileStream(
            $temporary, [System.IO.FileMode]::CreateNew, [System.Security.AccessControl.FileSystemRights]::Write,
            [System.IO.FileShare]::None, 4096, [System.IO.FileOptions]::WriteThrough, $security
        )
        $writer = New-Object System.IO.StreamWriter($stream, (New-Object System.Text.UTF8Encoding($false)))
        $writer.Write(($Value | ConvertTo-Json -Depth 30) + [Environment]::NewLine)
        $writer.Flush(); $stream.Flush($true)
        $writer.Dispose(); $writer = $null; $stream = $null
        $null = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $directoryRelative
        $null = Assert-Phase0RestrictedSchedulePath -Path $trustedDirectory -AccountSid $AccountSid.Value -Kind Directory
        if (Test-Path -LiteralPath $target) { throw 'Refusing to overwrite restricted schedule file' }
        [System.IO.File]::Move($temporary, $target)
        $null = Assert-Phase0RestrictedSchedulePath -Path $target -AccountSid $AccountSid.Value -Kind File
        return [pscustomobject]@{ path = $target; sha256 = Get-Phase0Sha256 -Path $target }
    }
    finally {
        if ($null -ne $writer) { $writer.Dispose(); $stream = $null }
        if ($null -ne $stream) { $stream.Dispose() }
        if (Test-Path -LiteralPath $temporary) { [System.IO.File]::Delete($temporary) }
    }
}

function Get-Phase0RunContext {
    param([string]$PackageRoot, [string]$CampaignId)
    $attempts = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath "work/campaigns/$CampaignId/attempts"
    $contexts = @()
    foreach ($directory in Get-ChildItem -LiteralPath $attempts -Force | Sort-Object Name -Descending) {
        if (-not $directory.PSIsContainer -or $directory.Name -notmatch '^attempt-[0-9]{4,10}$' -or
            ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Unexpected entry in attempts directory: $($directory.Name)"
        }
        $candidate = Join-Path $directory.FullName 'run-context.json'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $candidate
            $contexts += Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath $relative
        }
    }
    if ($contexts.Count -lt 1) { throw 'Prepared run-context.json is missing' }
    $context = [System.IO.File]::ReadAllText($contexts[0], [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    $expected = @('campaign_id', 'utc', 'umi_asset_sha256', 'umi_root_relative', 'umi_runtime_relative', 'umi_plugin_relative') | Sort-Object
    if (@(Compare-Object $expected @($context.PSObject.Properties.Name | Sort-Object)).Count -ne 0 -or
        $context.campaign_id -ne $CampaignId) { throw 'Prepared run context is invalid' }
    return $context
}

function Get-Phase0RunnerScript {
    param([string]$PackageRoot)
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $packaged = Join-Path $root 'toolkit/scripts/run-windows-validation.ps1'
    $runner = if (Test-Path -LiteralPath $packaged -PathType Leaf) { $packaged } else { Join-Path $root 'scripts/run-windows-validation.ps1' }
    $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $runner
    return Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $relative
}

function Get-Phase0RunnerConfiguration {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId, [ValidateSet('Interactive', 'Scheduled')][string]$ExecutionMode, $Attempt)
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $context = Get-Phase0RunContext -PackageRoot $root -CampaignId $CampaignId
    $runtimePython = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath ([string]$context.umi_runtime_relative)
    $plugin = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath ([string]$context.umi_plugin_relative)
    $projectRoot = if (Test-Path -LiteralPath (Join-Path $root 'toolkit/src') -PathType Container) { Join-Path $root 'toolkit' } else { $root }
    $mode = $ExecutionMode.ToLowerInvariant()
    return [pscustomobject][ordered]@{
        package_root = $root; project_root = $projectRoot
        umi_data_root = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetDirectoryName($runtimePython))
        test_python_exe = Join-Path $root 'runtime/python/python.exe'; python_exe = $runtimePython
        plugin_root = [System.IO.Path]::GetDirectoryName($plugin); plugin_name = [System.IO.Path]::GetFileName($plugin)
        global_options = Join-Path $root 'templates/global-options.json'; local_options = Join-Path $root 'templates/local-options.json'
        samples_manifest = Join-Path $root 'templates/samples.json'; validation_id = $ValidationId; campaign_id = $CampaignId
        execution_mode = $ExecutionMode; output_dir = Join-Path $Attempt.root "ocr/$mode/$ValidationId"
        min_pages = 100; business_concurrency_limit = 5
        stdout_log = Join-Path $Attempt.root "$mode-stdout.log"; stderr_log = Join-Path $Attempt.root "$mode-stderr.log"
        attempt = [int]$Attempt.number
    }
}

function Assert-Phase0RunnerConfiguration {
    param([string]$PackageRoot, $Configuration)
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $expectedProperties = @(
        'attempt', 'business_concurrency_limit', 'campaign_id', 'execution_mode', 'global_options', 'local_options',
        'min_pages', 'output_dir', 'package_root', 'plugin_name', 'plugin_root', 'project_root', 'python_exe',
        'samples_manifest', 'stderr_log', 'stdout_log', 'test_python_exe', 'umi_data_root', 'validation_id'
    ) | Sort-Object
    if (@(Compare-Object $expectedProperties @($Configuration.PSObject.Properties.Name | Sort-Object)).Count -ne 0) {
        throw 'Runner configuration contains unexpected or missing fields'
    }
    Assert-Phase0SchedulerIdentifier -Value ([string]$Configuration.campaign_id) -Name CampaignId
    Assert-Phase0SchedulerIdentifier -Value ([string]$Configuration.validation_id) -Name ValidationId
    if ([string]$Configuration.execution_mode -notin @('Interactive', 'Scheduled') -or
        [int]$Configuration.attempt -lt 1 -or [int]$Configuration.min_pages -lt 1 -or
        [int]$Configuration.business_concurrency_limit -lt 1) { throw 'Runner configuration scalar values are invalid' }
    if ($Configuration.validation_id -eq $Configuration.campaign_id) { throw 'ValidationId and CampaignId must be different' }
    Assert-Phase0ExactPath -Actual ([string]$Configuration.package_root) -Expected $root -Name package_root
    $campaign = [string]$Configuration.campaign_id
    $validation = [string]$Configuration.validation_id
    $attemptName = 'attempt-{0:D4}' -f [int]$Configuration.attempt
    $attemptRoot = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath "work/campaigns/$campaign/attempts/$attemptName"
    $expectedProject = if (Test-Path -LiteralPath (Join-Path $root 'toolkit/src')) { Join-Path $root 'toolkit' } else { $root }
    $umiData = Join-Path $root "work/campaigns/$campaign/umi/Umi-OCR_Rapid_v2.1.5/UmiOCR-data"
    $expected = [ordered]@{
        project_root = $expectedProject; umi_data_root = $umiData
        test_python_exe = Join-Path $root 'runtime/python/python.exe'; python_exe = Join-Path $umiData 'runtime/python.exe'
        plugin_root = Join-Path $umiData 'plugins'; global_options = Join-Path $root 'templates/global-options.json'
        local_options = Join-Path $root 'templates/local-options.json'; samples_manifest = Join-Path $root 'templates/samples.json'
        output_dir = Join-Path $attemptRoot ("ocr/" + ([string]$Configuration.execution_mode).ToLowerInvariant() + "/$validation")
    }
    foreach ($name in $expected.Keys) { Assert-Phase0ExactPath -Actual ([string]$Configuration.$name) -Expected $expected[$name] -Name $name }
    $mode = ([string]$Configuration.execution_mode).ToLowerInvariant()
    $hasStdout = -not [string]::IsNullOrWhiteSpace([string]$Configuration.stdout_log)
    $hasStderr = -not [string]::IsNullOrWhiteSpace([string]$Configuration.stderr_log)
    if ($hasStdout -ne $hasStderr) { throw 'Runner logs must be configured together' }
    if ($hasStdout) {
        Assert-Phase0ExactPath -Actual ([string]$Configuration.stdout_log) -Expected (Join-Path $attemptRoot "$mode-stdout.log") -Name stdout_log
        Assert-Phase0ExactPath -Actual ([string]$Configuration.stderr_log) -Expected (Join-Path $attemptRoot "$mode-stderr.log") -Name stderr_log
    }
    if ([string]$Configuration.plugin_name -ne 'win7_x64_RapidOCR-json') { throw 'Untrusted OCR plugin name' }
    foreach ($name in @('project_root', 'umi_data_root', 'test_python_exe', 'python_exe', 'plugin_root', 'global_options', 'local_options', 'samples_manifest')) {
        $path = [string]$Configuration.$name
        $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $path
        $null = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $relative
    }
    foreach ($path in @([string]$Configuration.output_dir, [string]$Configuration.stdout_log, [string]$Configuration.stderr_log)) {
        if ([string]::IsNullOrWhiteSpace($path)) { continue }
        $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $path
        $null = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $relative -AllowMissing
    }
    return [pscustomobject]@{ configuration = $Configuration; attempt_root = $attemptRoot }
}

function Get-Phase0InstallMetadataExpectedProperties {
    return @(
        'account_sid', 'argument_file_relative', 'argument_sha256', 'campaign_id', 'install_attempt', 'installed_at_utc',
        'installed_task_xml_sha256', 'schema_version', 'secure_directory_relative', 'structured_definition', 'task_name', 'validation_id'
    ) | Sort-Object
}

function Read-Phase0InstallMetadata {
    param([string]$PackageRoot, [string]$MetadataPath)
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $MetadataPath
    $trustedPath = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $relative
    $directory = [System.IO.Path]::GetDirectoryName($trustedPath)
    $accountSid = Assert-Phase0RestrictedSchedulePath -Path $directory -Kind Directory
    $null = Assert-Phase0RestrictedSchedulePath -Path $trustedPath -AccountSid $accountSid -Kind File
    $metadata = [System.IO.File]::ReadAllText($trustedPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    if (@(Compare-Object (Get-Phase0InstallMetadataExpectedProperties) @($metadata.PSObject.Properties.Name | Sort-Object)).Count -ne 0 -or
        $metadata.schema_version -ne '1.0' -or $metadata.account_sid -ne $accountSid) {
        throw 'Install metadata is invalid'
    }
    $expectedDefinitionProperties = @(
        'account_sid', 'action_count', 'argument_file_relative', 'arguments_sha256', 'execute',
        'execution_time_limit', 'logon_type', 'run_level', 'runner_relative', 'start_when_available'
    ) | Sort-Object
    if ($metadata.structured_definition -isnot [pscustomobject] -or
        @(Compare-Object $expectedDefinitionProperties @($metadata.structured_definition.PSObject.Properties.Name | Sort-Object)).Count -ne 0) {
        throw 'Install structured task definition is invalid'
    }
    return [pscustomobject]@{ path = $trustedPath; value = $metadata; account_sid = $accountSid }
}

function Read-Phase0TrustedRunnerArguments {
    param([string]$PackageRoot, [string]$ArgumentFile)
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $ArgumentFile
    $trustedArgument = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $relative
    $configuration = [System.IO.File]::ReadAllText($trustedArgument, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    $validated = Assert-Phase0RunnerConfiguration -PackageRoot $root -Configuration $configuration
    $campaign = [string]$configuration.campaign_id; $validation = [string]$configuration.validation_id
    $attemptName = 'attempt-{0:D4}' -f [int]$configuration.attempt
    if ($configuration.execution_mode -eq 'Scheduled') {
        $expectedArgumentRelative = "work/campaigns/$campaign/attempts/$attemptName/secure/schedule-$validation/arguments.json"
        if ($relative -ne $expectedArgumentRelative) { throw 'Scheduled argument file path is not trusted' }
        $metadataPath = Join-Path ([System.IO.Path]::GetDirectoryName($trustedArgument)) 'install-metadata.json'
        $metadataRecord = Read-Phase0InstallMetadata -PackageRoot $root -MetadataPath $metadataPath
        $metadata = $metadataRecord.value
        $secureParent = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetDirectoryName($trustedArgument))
        $attemptParent = [System.IO.Path]::GetDirectoryName($secureParent)
        $null = Assert-Phase0RestrictedSchedulePath -Path $attemptParent -AccountSid $metadata.account_sid -Kind Directory
        $null = Assert-Phase0RestrictedSchedulePath -Path $secureParent -AccountSid $metadata.account_sid -Kind Directory
        $null = Assert-Phase0RestrictedSchedulePath -Path $trustedArgument -AccountSid $metadata.account_sid -Kind File
        if ((Get-Phase0Sha256 -Path $trustedArgument) -ne $metadata.argument_sha256 -or
            $metadata.argument_file_relative -ne $relative -or $metadata.campaign_id -ne $campaign -or
            $metadata.validation_id -ne $validation -or [int]$metadata.install_attempt -ne [int]$configuration.attempt) {
            throw 'Scheduled argument file hash or binding mismatch'
        }
    }
    else {
        $expectedArgumentRelative = "work/campaigns/$campaign/attempts/$attemptName/interactive-arguments.json"
        if ($relative -ne $expectedArgumentRelative) { throw 'Interactive argument file path is not trusted' }
    }
    return $configuration
}

function Invoke-Phase0RunnerProcess {
    param([string]$PackageRoot, $Configuration, $Attempt)
    $argumentFile = Join-Path $Attempt.root 'interactive-arguments.json'
    $null = Write-Phase0SchedulerJson -PackageRoot $PackageRoot -Path $argumentFile -Value $Configuration
    $powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $powerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Get-Phase0RunnerScript $PackageRoot) -ArgumentFile $argumentFile
    return [int]$LASTEXITCODE
}

function Invoke-Phase0EvidenceValidator {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId, [string]$ExpectedMode, [string]$ResultsDir, $Attempt)
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $portablePython = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath 'runtime/python/python.exe'
    $projectRoot = if (Test-Path -LiteralPath (Join-Path $root 'toolkit/src')) { Join-Path $root 'toolkit' } else { $root }
    $output = Join-Path $Attempt.root ("$ExpectedMode-evidence-validation.json")
    $originalPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $projectRoot 'src'
        & $portablePython -m umi_web_spike.cli validate-ocr-evidence --results-dir $ResultsDir `
            --expected-mode $ExpectedMode --campaign-id $CampaignId --validation-id $ValidationId --output $output | Out-Host
        $exitCode = [int]$LASTEXITCODE
    }
    catch { $exitCode = 1 }
    finally { $env:PYTHONPATH = $originalPythonPath }
    if (Test-Path -LiteralPath $output -PathType Leaf) {
        try {
            $value = [System.IO.File]::ReadAllText($output, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
            if ($value.campaign_id -eq $CampaignId -and $value.validation_id -eq $ValidationId -and
                $value.expected_mode -eq $ExpectedMode -and $value.evidence_validation_ok -is [bool]) {
                return [pscustomobject]@{
                    ok = ($exitCode -eq 0 -and $value.evidence_validation_ok)
                    code = $value.validation_error_code
                    windows_session_id = $value.windows_session_id
                }
            }
        }
        catch { }
    }
    return [pscustomobject]@{ ok = $false; code = 'VALIDATOR_EXECUTION_FAILED'; windows_session_id = $null }
}

function Invoke-Phase0NativeProcess {
    param([string]$Executable, [string[]]$Arguments, [string]$StdoutLog = '', [string]$StderrLog = '')
    $useLogs = -not [string]::IsNullOrWhiteSpace($StdoutLog) -and -not [string]::IsNullOrWhiteSpace($StderrLog)
    if ($useLogs) {
        & $Executable @Arguments 1>> $StdoutLog 2>> $StderrLog
    }
    elseif ([string]::IsNullOrWhiteSpace($StdoutLog) -and [string]::IsNullOrWhiteSpace($StderrLog)) {
        & $Executable @Arguments | Out-Host
    }
    else { throw 'Native process logs must be configured together' }
    $exitCode = [int]$LASTEXITCODE
    return [int]$exitCode
}

function New-Phase0PublishedFailure {
    param([string]$Message)
    $exception = New-Object System.InvalidOperationException($Message)
    $exception.Data['Phase0StatePublished'] = $true
    return $exception
}

function Invoke-InteractiveValidation {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId)
    Assert-Phase0SchedulerIdentifier -Value $ValidationId -Name ValidationId
    $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
    if ($state.state -notin @('SELF_TEST_PASSED', 'INTERACTIVE_OCR_FAILED')) {
        throw 'Interactive validation requires SELF_TEST_PASSED or INTERACTIVE_OCR_FAILED'
    }
    if ($state.state -eq 'INTERACTIVE_OCR_FAILED' -and $state.interactive_validation_id -ne $ValidationId) {
        throw 'Interactive retry must retain its declared validation ID'
    }
    $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId
    $runnerExit = -1; $validator = [pscustomobject]@{ ok = $false; code = 'RUNNER_SETUP_FAILED'; windows_session_id = $null }; $outputDir = $null
    try {
        $configuration = Get-Phase0RunnerConfiguration -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -ExecutionMode Interactive -Attempt $attempt
        $null = Assert-Phase0RunnerConfiguration -PackageRoot $PackageRoot -Configuration $configuration
        $outputDir = $configuration.output_dir
        $runnerExit = Invoke-Phase0RunnerProcess -PackageRoot $PackageRoot -Configuration $configuration -Attempt $attempt
        $validator = Invoke-Phase0EvidenceValidator -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId `
            -ExpectedMode interactive -ResultsDir $outputDir -Attempt $attempt
    }
    catch { $validator = [pscustomobject]@{ ok = $false; code = 'RUNNER_OR_PATH_VALIDATION_FAILED'; windows_session_id = $null } }
    $passed = $runnerExit -eq 0 -and $validator.ok
    $summary = [ordered]@{
        campaign_id = $CampaignId; validation_id = $ValidationId; execution_mode = 'interactive'
        collection_attempt = $attempt.number; recorded_at_utc = [DateTime]::UtcNow.ToString('o')
        runner_exit_code = $runnerExit; evidence_validation_ok = [bool]$validator.ok
        validation_error_code = $validator.code; windows_session_id = $validator.windows_session_id
        result = if ($passed) { 'passed' } else { 'failed' }
    }
    $summaryPath = Write-Phase0SchedulerJson -PackageRoot $PackageRoot -Path (Join-Path $attempt.root 'interactive-validation-summary.json') -Value $summary
    $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $summaryPath
    $nextState = if ($passed) { 'INTERACTIVE_OCR_PASSED' } else { 'INTERACTIVE_OCR_FAILED' }
    $null = Set-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId -NewState $nextState -Attempt $attempt.number `
        -EvidenceRelativePath $relative -ValidationKind Interactive -ValidationId $ValidationId
    if (-not $passed) { throw (New-Phase0PublishedFailure 'Interactive OCR validation failed') }
    return [pscustomobject]$summary
}

function New-Phase0TaskDefinition {
    param([string]$ValidationId, [string]$CommandPath, [string]$RunnerPath, [string]$ArgumentFile, [string]$AccountSid = '<credential-required>')
    Assert-Phase0SchedulerIdentifier -Value $ValidationId -Name ValidationId
    return [pscustomobject][ordered]@{
        task_name = "UmiOcrPhase0-$ValidationId"; execute = $CommandPath
        arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$RunnerPath`" -ArgumentFile `"$ArgumentFile`""
        argument_file = $ArgumentFile; account_sid = $AccountSid; logon_type = 'Password'; run_level = 'Highest'
        execution_time_limit = 'PT6H'; start_when_available = $true; action_count = 1
    }
}

function Get-Phase0CollectionRecords {
    param([string]$PackageRoot, [string]$CampaignId)
    $attempts = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath "work/campaigns/$CampaignId/attempts"
    $campaignState = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
    $records = @()
    foreach ($directory in Get-ChildItem -LiteralPath $attempts -Force) {
        if (-not $directory.PSIsContainer -or $directory.Name -notmatch '^attempt-[0-9]{4,10}$' -or
            ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Unexpected attempts entry' }
        $summary = Join-Path $directory.FullName 'scheduled-collection.json'
        if (-not (Test-Path -LiteralPath $summary -PathType Leaf)) { continue }
        $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $summary
        $summary = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath $relative
        try { $value = [System.IO.File]::ReadAllText($summary, [System.Text.Encoding]::UTF8) | ConvertFrom-Json }
        catch { continue }
        $transition = Join-Path $directory.FullName ("state-transition-" + [string]$value.state + '.json')
        if (Test-Path -LiteralPath $transition -PathType Leaf) {
            try { $transitionValue = [System.IO.File]::ReadAllText($transition, [System.Text.Encoding]::UTF8) | ConvertFrom-Json }
            catch { continue }
            $expectedEvidence = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $summary
            $attemptNumber = [int]($directory.Name.Substring('attempt-'.Length))
            if ($value.campaign_id -eq $CampaignId -and [int]$value.collection_attempt -eq $attemptNumber -and
                $value.final -is [bool] -and $transitionValue.campaign_id -eq $CampaignId -and
                [int]$transitionValue.attempt -eq $attemptNumber -and
                $transitionValue.evidence_relative_path -eq $expectedEvidence -and $transitionValue.state -eq $value.state) {
                if ([int]$campaignState.attempt -ge $attemptNumber) { $records += $value }
            }
        }
    }
    return $records
}

function Get-Phase0ScheduleRecords {
    param([string]$PackageRoot, [string]$CampaignId)
    $attempts = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath "work/campaigns/$CampaignId/attempts"
    $collections = @(Get-Phase0CollectionRecords -PackageRoot $PackageRoot -CampaignId $CampaignId)
    $records = @()
    foreach ($directory in Get-ChildItem -LiteralPath $attempts -Force) {
        if (-not $directory.PSIsContainer -or $directory.Name -notmatch '^attempt-[0-9]{4,10}$' -or
            ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Unexpected attempts entry' }
        $secure = Join-Path $directory.FullName 'secure'
        if (-not (Test-Path -LiteralPath $secure -PathType Container)) { continue }
        $secureAccount = Assert-Phase0RestrictedSchedulePath -Path $secure -Kind Directory
        $null = Assert-Phase0RestrictedSchedulePath -Path $directory.FullName -AccountSid $secureAccount -Kind Directory
        foreach ($scheduleDirectory in Get-ChildItem -LiteralPath $secure -Force) {
            if (-not $scheduleDirectory.PSIsContainer) { throw 'Unexpected file in secure schedule root' }
            if ($scheduleDirectory.Name -notmatch '^schedule-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' -or
                ($scheduleDirectory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Unexpected secure schedule entry' }
            $metadataPath = Join-Path $scheduleDirectory.FullName 'install-metadata.json'
            if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) { continue }
            $metadata = (Read-Phase0InstallMetadata -PackageRoot $PackageRoot -MetadataPath $metadataPath).value
            if ($metadata.account_sid -ne $secureAccount) { throw 'Secure directory execution SID mismatch' }
            if ($metadata.campaign_id -ne $CampaignId) { throw 'Schedule campaign binding mismatch' }
            $attemptNumber = [int]($directory.Name.Substring('attempt-'.Length))
            $attemptRelative = "work/campaigns/$CampaignId/attempts/$($directory.Name)"
            $expectedSecure = "$attemptRelative/secure/schedule-$($metadata.validation_id)"
            $expectedArgument = "$expectedSecure/arguments.json"
            if ([int]$metadata.install_attempt -ne $attemptNumber -or
                $scheduleDirectory.Name -ne "schedule-$($metadata.validation_id)" -or
                $metadata.task_name -ne "UmiOcrPhase0-$($metadata.validation_id)" -or
                $metadata.secure_directory_relative -ne $expectedSecure -or
                $metadata.argument_file_relative -ne $expectedArgument -or
                [string]$metadata.argument_sha256 -notmatch '^[0-9a-f]{64}$' -or
                [string]$metadata.installed_task_xml_sha256 -notmatch '^[0-9a-f]{64}$') {
                throw 'Install metadata path or hash binding mismatch'
            }
            $finalCollections = @($collections | Where-Object {
                $_.validation_id -eq $metadata.validation_id -and [int]$_.install_attempt -eq [int]$metadata.install_attempt -and $_.final -eq $true
            })
            $records += [pscustomobject]@{ metadata = $metadata; metadata_path = $metadataPath; final = ($finalCollections.Count -gt 0) }
        }
    }
    return $records
}

function Get-Phase0PendingSchedule {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId = '')
    $pending = @(Get-Phase0ScheduleRecords -PackageRoot $PackageRoot -CampaignId $CampaignId | Where-Object { -not $_.final })
    if ($pending.Count -gt 1) { throw 'Only one uncollected scheduled task is allowed per campaign' }
    if (-not [string]::IsNullOrWhiteSpace($ValidationId)) { $pending = @($pending | Where-Object { $_.metadata.validation_id -eq $ValidationId }) }
    if ($pending.Count -ne 1) { throw 'Expected exactly one pending scheduled task for the declared validation ID' }
    return $pending[0]
}

function Move-Phase0InstallMetadataToTerminal {
    param($Schedule, [ValidateSet('cleaned', 'start-failed')][string]$Reason)
    $source = [string]$Schedule.metadata_path
    $directory = [System.IO.Path]::GetDirectoryName($source)
    $accountSid = Assert-Phase0RestrictedSchedulePath -Path $directory -Kind Directory
    $null = Assert-Phase0RestrictedSchedulePath -Path $source -AccountSid $accountSid -Kind File
    $target = Join-Path $directory ("install-terminal-$Reason.json")
    if (Test-Path -LiteralPath $target) { throw 'Terminal install metadata already exists' }
    [System.IO.File]::Move($source, $target)
    $null = Assert-Phase0RestrictedSchedulePath -Path $target -AccountSid $accountSid -Kind File
    return $target
}

function Install-Phase0ScheduledTask {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId,
        [string]$CommandPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe",
        [System.Management.Automation.PSCredential]$Credential, [switch]$DryRun)
    Assert-Phase0SchedulerIdentifier -Value $ValidationId -Name ValidationId
    $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
    if ($state.state -notin @('INTERACTIVE_OCR_PASSED', 'SCHEDULED_OCR_FAILED')) {
        throw 'Scheduled install requires INTERACTIVE_OCR_PASSED or SCHEDULED_OCR_FAILED'
    }
    if ($state.interactive_validation_id -eq $ValidationId) { throw 'Interactive and scheduled validation IDs must be different' }
    if ($state.state -eq 'SCHEDULED_OCR_FAILED' -and $state.scheduled_validation_id -ne $ValidationId) {
        throw 'Scheduled retry must retain its declared validation ID'
    }
    $allSchedules = @(Get-Phase0ScheduleRecords -PackageRoot $PackageRoot -CampaignId $CampaignId)
    if (@($allSchedules | Where-Object { -not $_.final }).Count -gt 0) {
        throw 'Only one uncollected scheduled task is allowed per campaign'
    }
    $TaskName = "UmiOcrPhase0-$ValidationId"
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw "Scheduled task already exists: $TaskName" }
    if ($DryRun) {
        $dryRunDefinition = New-Phase0TaskDefinition -ValidationId $ValidationId -CommandPath $CommandPath `
            -RunnerPath (Get-Phase0RunnerScript $PackageRoot) -ArgumentFile '<restricted-argument-file>'
        return $dryRunDefinition
    }
    if ($null -eq $Credential) { $Credential = Get-Credential -Message 'Phase 0 scheduled-task account' }
    $userName = $Credential.UserName
    $accountSid = (New-Object System.Security.Principal.NTAccount($userName)).Translate([System.Security.Principal.SecurityIdentifier])
    $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId
    $configuration = Get-Phase0RunnerConfiguration -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -ExecutionMode Scheduled -Attempt $attempt
    $null = Assert-Phase0RunnerConfiguration -PackageRoot $PackageRoot -Configuration $configuration
    $secureDirectory = New-Phase0RestrictedScheduleDirectory -PackageRoot $PackageRoot -Attempt $attempt -ValidationId $ValidationId -AccountSid $accountSid
    $argumentRecord = Write-Phase0RestrictedJsonAtomic -PackageRoot $PackageRoot -Directory $secureDirectory -Name 'arguments.json' -Value $configuration -AccountSid $accountSid
    $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
    $expectedPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    Assert-Phase0ExactPath -Actual $CommandPath -Expected $expectedPowerShell -Name CommandPath
    $definition = New-Phase0TaskDefinition -ValidationId $ValidationId -CommandPath $expectedPowerShell `
        -RunnerPath (Get-Phase0RunnerScript $root) -ArgumentFile $argumentRecord.path -AccountSid $accountSid.Value
    $TaskAction = New-ScheduledTaskAction -Execute $definition.execute -Argument $definition.arguments
    $TaskSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 6) -StartWhenAvailable
    $TaskPrincipal = New-ScheduledTaskPrincipal -UserId $accountSid.Value -LogonType Password -RunLevel Highest
    $TaskDefinition = New-ScheduledTask -Action $TaskAction -Settings $TaskSettings -Principal $TaskPrincipal
    $PlainPassword = $Credential.GetNetworkCredential().Password
    try { Register-ScheduledTask -TaskName $TaskName -InputObject $TaskDefinition -User $userName -Password $PlainPassword | Out-Null }
    finally { $PlainPassword = $null; $Credential = $null }
    $installedXml = Export-ScheduledTask -TaskName $TaskName
    $argumentRelative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $argumentRecord.path
    $secureRelative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path $secureDirectory
    $structuredDefinition = [ordered]@{
        account_sid = $accountSid.Value; execute = $definition.execute
        runner_relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $root -Path (Get-Phase0RunnerScript $root)
        argument_file_relative = $argumentRelative; arguments_sha256 = Get-Phase0TextSha256 -Text $definition.arguments
        logon_type = 'Password'; run_level = 'HighestAvailable'; execution_time_limit = 'PT6H'
        start_when_available = $true; action_count = 1
    }
    $metadata = [ordered]@{
        schema_version = '1.0'; campaign_id = $CampaignId; validation_id = $ValidationId; install_attempt = $attempt.number
        task_name = $TaskName; installed_at_utc = [DateTime]::UtcNow.ToString('o'); account_sid = $accountSid.Value
        secure_directory_relative = $secureRelative; argument_file_relative = $argumentRelative
        argument_sha256 = $argumentRecord.sha256; structured_definition = $structuredDefinition
        installed_task_xml_sha256 = Get-Phase0TextSha256 -Text $installedXml
    }
    if (-not (Test-Phase0InstalledTaskXml -PackageRoot $root -Metadata ([pscustomobject]$metadata) -TaskXml $installedXml)) {
        throw 'Installed scheduled task does not match the intended definition'
    }
    $metadataRecord = Write-Phase0RestrictedJsonAtomic -PackageRoot $root -Directory $secureDirectory -Name 'install-metadata.json' -Value $metadata -AccountSid $accountSid
    $schedule = [pscustomobject]@{ metadata = [pscustomobject]$metadata; metadata_path = $metadataRecord.path; final = $false }
    try { Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop }
    catch {
        $startFailure = $_
        try {
            $null = Publish-Phase0ScheduledCollection -PackageRoot $root -CampaignId $CampaignId -Schedule $schedule `
                -Passed $false -Final $true -LastTaskResult -1 -ValidationErrorCode 'SCHEDULED_TASK_START_FAILED' `
                -TaskDefinitionValid $true -Configuration $configuration -TaskXmlSha256 $metadata.installed_task_xml_sha256 `
                -LifecycleStatus 'terminal-start-failed'
        }
        catch {
            if ($_.Exception.Data['Phase0StatePublished']) { throw }
            try {
                if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
                    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
                }
                $null = Move-Phase0InstallMetadataToTerminal -Schedule $schedule -Reason 'start-failed'
            }
            catch { throw 'Scheduled task start failed and lifecycle compensation also failed' }
            throw $startFailure
        }
    }
    return $definition
}

function Test-Phase0InstalledTaskXml {
    param([string]$PackageRoot, $Metadata, [string]$TaskXml)
    if ((Get-Phase0TextSha256 -Text $TaskXml) -ne $Metadata.installed_task_xml_sha256) { return $false }
    try {
        [xml]$document = $TaskXml
        $Principal = $document.SelectSingleNode("//*[local-name()='Principal']")
        $UserId = $Principal.SelectSingleNode("./*[local-name()='UserId']").InnerText
        $LogonType = $Principal.SelectSingleNode("./*[local-name()='LogonType']").InnerText
        $RunLevel = $Principal.SelectSingleNode("./*[local-name()='RunLevel']").InnerText
        $StartWhenAvailable = $document.SelectSingleNode("//*[local-name()='StartWhenAvailable']").InnerText
        $limit = $document.SelectSingleNode("//*[local-name()='ExecutionTimeLimit']").InnerText
        $ActionNodes = $document.SelectNodes("//*[local-name()='Actions']/*")
        $ExecNodes = $document.SelectNodes("//*[local-name()='Actions']/*[local-name()='Exec']")
        if ($ActionNodes.Count -eq 1 -and $ExecNodes.Count -eq 1) { $exec = $ExecNodes[0] } else { return $false }
        $command = $exec.SelectSingleNode("./*[local-name()='Command']").InnerText
        $arguments = $exec.SelectSingleNode("./*[local-name()='Arguments']").InnerText
        $root = Get-Phase0SchedulerRoot -PackageRoot $PackageRoot
        $argumentFile = Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $Metadata.argument_file_relative
        $expected = New-Phase0TaskDefinition -ValidationId $Metadata.validation_id `
            -CommandPath (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') `
            -RunnerPath (Resolve-Phase0SchedulerPath -PackageRoot $root -RelativePath $Metadata.structured_definition.runner_relative) `
            -ArgumentFile $argumentFile -AccountSid $Metadata.account_sid
        $structured = $Metadata.structured_definition
        return $UserId -eq $Metadata.account_sid -and $LogonType -eq 'Password' -and $RunLevel -eq 'HighestAvailable' -and
            $StartWhenAvailable -eq 'true' -and $limit -eq 'PT6H' -and $ActionNodes.Count -eq 1 -and $ExecNodes.Count -eq 1 -and
            $command -eq $expected.execute -and $arguments -eq $expected.arguments -and
            (Get-Phase0TextSha256 -Text $arguments) -eq $structured.arguments_sha256 -and
            $structured.account_sid -eq $Metadata.account_sid -and $structured.execute -eq $expected.execute -and
            $structured.argument_file_relative -eq $Metadata.argument_file_relative -and $structured.logon_type -eq 'Password' -and
            $structured.run_level -eq 'HighestAvailable' -and $structured.execution_time_limit -eq 'PT6H' -and
            $structured.start_when_available -eq $true -and [int]$structured.action_count -eq 1
    }
    catch { return $false }
}

function Get-Phase0LogSummary {
    param([string]$PackageRoot, [string]$Path)
    $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $Path
    $trusted = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath $relative -AllowMissing
    if (-not (Test-Path -LiteralPath $trusted -PathType Leaf)) { return [ordered]@{ path = $relative; exists = $false; length = 0; sha256 = $null } }
    $item = Get-Item -LiteralPath $trusted
    return [ordered]@{ path = $relative; exists = $true; length = [int64]$item.Length; sha256 = Get-Phase0Sha256 $trusted }
}

function Publish-Phase0ScheduledCollection {
    param([string]$PackageRoot, [string]$CampaignId, $Schedule, [bool]$Passed, [bool]$Final,
        [int64]$LastTaskResult, [string]$ValidationErrorCode, [bool]$TaskDefinitionValid, $Configuration,
        $Attempt = $null, $WindowsSessionId = $null, [bool]$EvidenceValidationOk = $false,
        [string]$TaskXmlSha256 = '', [string]$StartedAtUtc = '', [string]$LifecycleStatus = '',
        [bool]$ThrowOnFailure = $true)
    $attempt = $Attempt
    if ($null -eq $attempt) { $attempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId }
    $metadata = $Schedule.metadata
    $stateName = if ($Passed) { 'SCHEDULED_OCR_PASSED' } else { 'SCHEDULED_OCR_FAILED' }
    if ([string]::IsNullOrWhiteSpace($LifecycleStatus)) {
        $LifecycleStatus = if (-not $Final) { 'pending-collection-retry' } elseif ($Passed) { 'terminal-passed' } else { 'terminal-failed' }
    }
    $logs = @()
    if ($null -ne $Configuration) {
        $logs = @(
            Get-Phase0LogSummary -PackageRoot $PackageRoot -Path $Configuration.stdout_log
            Get-Phase0LogSummary -PackageRoot $PackageRoot -Path $Configuration.stderr_log
        )
    }
    $summary = [ordered]@{
        campaign_id = $CampaignId; validation_id = $metadata.validation_id; install_attempt = [int]$metadata.install_attempt
        collection_attempt = $attempt.number; recorded_at_utc = [DateTime]::UtcNow.ToString('o')
        started_at_utc = $StartedAtUtc; ended_at_utc = [DateTime]::UtcNow.ToString('o')
        LastTaskResult = $LastTaskResult; task_definition_valid = $TaskDefinitionValid
        task_xml_sha256 = $TaskXmlSha256
        evidence_validation_ok = $EvidenceValidationOk; validation_error_code = $ValidationErrorCode
        windows_session_id = $WindowsSessionId
        log_summaries = $logs; final = $Final; lifecycle_status = $LifecycleStatus
        state = $stateName; result = if ($Passed) { 'passed' } else { 'failed' }
    }
    $path = Write-Phase0SchedulerJson -PackageRoot $PackageRoot -Path (Join-Path $attempt.root 'scheduled-collection.json') -Value $summary
    $relative = ConvertTo-Phase0SchedulerRelativePath -PackageRoot $PackageRoot -Path $path
    $null = Set-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId -NewState $stateName -Attempt $attempt.number `
        -EvidenceRelativePath $relative -ValidationKind Scheduled -ValidationId $metadata.validation_id
    if (-not $Passed -and $ThrowOnFailure) { throw (New-Phase0PublishedFailure 'Scheduled OCR validation failed') }
    return [pscustomobject]$summary
}

function Collect-Phase0ScheduledTask {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId)
    Assert-Phase0SchedulerIdentifier -Value $ValidationId -Name ValidationId
    $state = Get-Phase0State -PackageRoot $PackageRoot -CampaignId $CampaignId
    if ($state.state -notin @('INTERACTIVE_OCR_PASSED', 'SCHEDULED_OCR_FAILED')) {
        throw 'Scheduled collection requires INTERACTIVE_OCR_PASSED or SCHEDULED_OCR_FAILED'
    }
    if ($state.state -eq 'SCHEDULED_OCR_FAILED' -and $state.scheduled_validation_id -ne $ValidationId) {
        throw 'Scheduled collection retry must retain its declared validation ID'
    }
    $schedule = Get-Phase0PendingSchedule -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId
    $metadata = $schedule.metadata; $TaskName = "UmiOcrPhase0-$ValidationId"
    $installedAt = [DateTime]::MinValue
    if (-not [DateTime]::TryParse([string]$metadata.installed_at_utc, [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind, [ref]$installedAt) -or $installedAt.Kind -ne [DateTimeKind]::Utc) {
        throw 'Installed task timestamp is invalid'
    }
    $deadline = $installedAt.Add((New-TimeSpan -Hours 6))
    do {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
        $hasStarted = $taskInfo.LastRunTime -gt [DateTime]'1601-01-02T00:00:00Z'
        if ([string]$task.State -notin @('Running', 'Queued') -and $hasStarted) { break }
        if ([DateTime]::UtcNow -ge $deadline) {
            $timeoutResult = Publish-Phase0ScheduledCollection -PackageRoot $PackageRoot -CampaignId $CampaignId -Schedule $schedule `
                -Passed $false -Final $true -LastTaskResult ([int64]$taskInfo.LastTaskResult) `
                -ValidationErrorCode 'SCHEDULED_TASK_TIMEOUT' -TaskDefinitionValid $false -Configuration $null
            return $timeoutResult
        }
        Start-Sleep -Seconds 5
    } while ($true)
    $taskXml = Export-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $taskXmlSha256 = Get-Phase0TextSha256 -Text $taskXml
    $startedAtUtc = $taskInfo.LastRunTime.ToUniversalTime().ToString('o')
    $configuration = $null; $argumentTrusted = $false; $collectionAttempt = $null
    try {
        $argumentFile = Resolve-Phase0SchedulerPath -PackageRoot $PackageRoot -RelativePath $metadata.argument_file_relative
        $configuration = Read-Phase0TrustedRunnerArguments -PackageRoot $PackageRoot -ArgumentFile $argumentFile
        $argumentTrusted = $true
    }
    catch { $argumentTrusted = $false }
    $definitionValid = Test-Phase0InstalledTaskXml -PackageRoot $PackageRoot -Metadata $metadata -TaskXml $taskXml
    $lastResult = [int64]$taskInfo.LastTaskResult
    $validator = [pscustomobject]@{ ok = $false; code = 'ARGUMENT_OR_TASK_DEFINITION_INVALID'; windows_session_id = $null }
    if ($argumentTrusted -and $definitionValid) {
        # The validator output belongs to the fresh collection attempt, so reserve it only after terminal task state.
        $collectionAttempt = Get-Phase0AttemptContext -PackageRoot $PackageRoot -CampaignId $CampaignId
        $validator = Invoke-Phase0EvidenceValidator -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId `
            -ExpectedMode scheduled -ResultsDir $configuration.output_dir -Attempt $collectionAttempt
    }
    $passed = $lastResult -eq 0 -and $argumentTrusted -and $definitionValid -and $validator.ok
    $errorCode = if ($passed) { $null } elseif (-not $argumentTrusted) { 'ARGUMENT_INTEGRITY_FAILED' } `
        elseif (-not $definitionValid) { 'TASK_DEFINITION_MISMATCH' } elseif ($lastResult -ne 0) { 'TASK_RESULT_NONZERO' } else { [string]$validator.code }
    $final = $passed -or -not $argumentTrusted -or -not $definitionValid -or $lastResult -ne 0
    $collectionResult = Publish-Phase0ScheduledCollection -PackageRoot $PackageRoot -CampaignId $CampaignId -Schedule $schedule `
        -Passed $passed -Final $final -LastTaskResult $lastResult -ValidationErrorCode $errorCode `
        -TaskDefinitionValid $definitionValid -Configuration $configuration -Attempt $collectionAttempt `
        -WindowsSessionId $validator.windows_session_id -EvidenceValidationOk ([bool]$validator.ok) `
        -TaskXmlSha256 $taskXmlSha256 -StartedAtUtc $startedAtUtc
    return $collectionResult
}

function Remove-Phase0ScheduledTask {
    param([string]$PackageRoot, [string]$CampaignId, [string]$ValidationId, [switch]$ConfirmCleanup)
    if (-not $ConfirmCleanup) { throw 'ConfirmCleanup is required' }
    Assert-Phase0SchedulerIdentifier -Value $ValidationId -Name ValidationId
    $schedules = @(Get-Phase0ScheduleRecords -PackageRoot $PackageRoot -CampaignId $CampaignId | Where-Object {
        $_.metadata.validation_id -eq $ValidationId
    })
    if ($schedules.Count -lt 1) { throw 'No scheduled-task lifecycle record exists for cleanup' }
    $pending = @($schedules | Where-Object { -not $_.final })
    if ($pending.Count -gt 1) { throw 'Only one uncollected scheduled task is allowed per campaign' }
    $TaskName = "UmiOcrPhase0-$ValidationId"
    $null = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    if ($pending.Count -eq 1) {
        try {
            return Publish-Phase0ScheduledCollection -PackageRoot $PackageRoot -CampaignId $CampaignId -Schedule $pending[0] `
                -Passed $false -Final $true -LastTaskResult -1 -ValidationErrorCode 'SCHEDULED_TASK_CLEANED' `
                -TaskDefinitionValid $false -Configuration $null -LifecycleStatus 'terminal-cleaned' -ThrowOnFailure $false
        }
        catch {
            $null = Move-Phase0InstallMetadataToTerminal -Schedule $pending[0] -Reason 'cleaned'
            throw
        }
    }
    return [pscustomobject]@{ validation_id = $ValidationId; lifecycle_status = 'terminal-cleaned'; final = $true }
}

Export-ModuleMember -Function @(
    'Assert-Phase0RunnerConfiguration', 'Read-Phase0TrustedRunnerArguments', 'Invoke-Phase0NativeProcess',
    'Invoke-InteractiveValidation', 'New-Phase0TaskDefinition', 'Install-Phase0ScheduledTask',
    'Collect-Phase0ScheduledTask', 'Remove-Phase0ScheduledTask'
)
