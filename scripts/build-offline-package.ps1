param(
  [string]$RepositoryRoot = (Resolve-Path "$PSScriptRoot\..").Path,
  [string]$LockPath = "$RepositoryRoot\packaging\offline-package.lock.json",
  [string]$CacheDir = "$RepositoryRoot\downloads",
  [string]$OutputDir = "$RepositoryRoot\dist",
  [switch]$OfflineCacheOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$PackageDirectoryName = "umi-ocr-phase0"
$ExpectedArchiveName = "umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip"
$FixedTimestamp = [DateTimeOffset]::Parse("2000-01-01T00:00:00Z")
$OnsiteReadmeName = "README-" + [char]0x73B0 + [char]0x573A + [char]0x9A8C + [char]0x8BC1 + ".md"

function Assert-NoReparsePath {
  param([string]$Path)

  $FullPath = [IO.Path]::GetFullPath($Path)
  $Current = $FullPath
  while (-not [string]::IsNullOrEmpty($Current)) {
    $Item = $null
    if (Test-Path -LiteralPath $Current) {
      $Item = Get-Item -LiteralPath $Current -Force
    }
    else {
      $CurrentParent = [IO.Directory]::GetParent($Current)
      if ($null -ne $CurrentParent -and (Test-Path -LiteralPath $CurrentParent.FullName -PathType Container)) {
        $CurrentName = [IO.Path]::GetFileName($Current)
        $Item = Get-ChildItem -LiteralPath $CurrentParent.FullName -Force |
          Where-Object { $_.Name -ieq $CurrentName } |
          Select-Object -First 1
      }
    }
    if ($null -ne $Item) {
      if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Symlink or reparse point is forbidden: $Current"
      }
    }
    $Parent = [IO.Directory]::GetParent($Current)
    if ($null -eq $Parent) { break }
    $Current = $Parent.FullName
  }
  return $FullPath
}

function Get-SafeContainedPath {
  param([string]$Root, [string]$Path)

  $FullRoot = (Assert-NoReparsePath -Path $Root).TrimEnd("\")
  $FullPath = Assert-NoReparsePath -Path $Path
  $Prefix = $FullRoot + "\"
  if ($FullPath -cne $FullRoot -and -not $FullPath.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Path escapes its trusted root: $Path"
  }
  return $FullPath
}

function Assert-NoReparseTree {
  param([string]$Root)

  $FullRoot = Assert-NoReparsePath -Path $Root
  if (-not (Test-Path -LiteralPath $FullRoot -PathType Container)) {
    throw "Expected a regular directory: $FullRoot"
  }
  foreach ($Child in @(Get-ChildItem -LiteralPath $FullRoot -Force)) {
    if (($Child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "Symlink or reparse point is forbidden: $($Child.FullName)"
    }
    if ($Child.PSIsContainer) {
      Assert-NoReparseTree -Root $Child.FullName
    }
  }
  return $FullRoot
}

function Remove-SafeFile {
  param([string]$Path)
  $SafePath = Assert-NoReparsePath -Path $Path
  if (Test-Path -LiteralPath $SafePath) {
    $Item = Get-Item -LiteralPath $SafePath -Force
    if ($Item.PSIsContainer) { throw "Refusing to remove a directory as a file: $SafePath" }
    Remove-Item -LiteralPath $SafePath -Force
  }
}

function Remove-SafeTree {
  param([string]$Path)
  $SafePath = Assert-NoReparsePath -Path $Path
  if (Test-Path -LiteralPath $SafePath) {
    Assert-NoReparseTree -Root $SafePath | Out-Null
    Remove-Item -LiteralPath $SafePath -Recurse -Force
  }
}

function Copy-PlainFile {
  param(
    [string]$SourceRoot,
    [string]$Source,
    [string]$DestinationRoot,
    [string]$Destination
  )

  $SafeSource = Get-SafeContainedPath -Root $SourceRoot -Path $Source
  if (-not (Test-Path -LiteralPath $SafeSource -PathType Leaf)) { throw "Copy source is not a regular file: $SafeSource" }
  $SafeDestination = Get-SafeContainedPath -Root $DestinationRoot -Path $Destination
  if (Test-Path -LiteralPath $SafeDestination -PathType Container) {
    throw "Copy destination must not be a directory: $SafeDestination"
  }
  $Parent = Split-Path -Parent $SafeDestination
  Assert-NoReparsePath -Path $Parent | Out-Null
  New-Item -ItemType Directory -Path $Parent -Force | Out-Null
  Assert-NoReparsePath -Path $Parent | Out-Null
  Copy-Item -LiteralPath $SafeSource -Destination $SafeDestination
  Assert-NoReparsePath -Path $SafeDestination | Out-Null
}

function Assert-LockedFile {
  param([string]$Path, [object]$Entry)

  $Path = Assert-NoReparsePath -Path $Path
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Locked asset is missing: $Path"
  }
  $File = Get-Item -LiteralPath $Path
  if ([int64]$File.Length -ne [int64]$Entry.size) {
    throw "Locked asset Length mismatch: $($Entry.name)"
  }
  $Digest = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($Digest -cne [string]$Entry.sha256) {
    throw "Locked asset SHA-256 mismatch: $($Entry.name)"
  }
}

function Get-LockedAsset {
  param([object]$Entry)

  $FinalPath = Get-SafeContainedPath -Root $CacheDir -Path (Join-Path $CacheDir ([string]$Entry.name))
  if ((Test-Path -LiteralPath $FinalPath) -and -not (Test-Path -LiteralPath $FinalPath -PathType Leaf)) {
    throw "Locked asset cache path is not a regular file: $FinalPath"
  }
  if (Test-Path -LiteralPath $FinalPath -PathType Leaf) {
    Assert-LockedFile -Path $FinalPath -Entry $Entry
    return $FinalPath
  }
  if ($OfflineCacheOnly) {
    throw "OfflineCacheOnly: locked asset is not cached: $($Entry.name)"
  }
  if (-not $Entry.PSObject.Properties["url"] -or [string]::IsNullOrWhiteSpace([string]$Entry.url)) {
    throw "Locked asset has no download URL: $($Entry.name)"
  }

  $PartialPath = Get-SafeContainedPath -Root $CacheDir -Path "$FinalPath.partial"
  Remove-SafeFile -Path $PartialPath
  try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri ([string]$Entry.url) -OutFile $PartialPath -UseBasicParsing
    Assert-LockedFile -Path $PartialPath -Entry $Entry
    Move-Item -LiteralPath $PartialPath -Destination $FinalPath
    Assert-LockedFile -Path $FinalPath -Entry $Entry
    return $FinalPath
  }
  catch {
    Remove-SafeFile -Path $PartialPath
    throw
  }
}

function Get-RelativePath {
  param([string]$Base, [string]$Path)

  $ResolvedBase = (Resolve-Path -LiteralPath $Base).Path.TrimEnd("\") + "\"
  $ResolvedPath = (Resolve-Path -LiteralPath $Path).Path
  if (-not $ResolvedPath.StartsWith($ResolvedBase, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Path is outside the expected root: $Path"
  }
  return $ResolvedPath.Substring($ResolvedBase.Length).Replace("\", "/")
}

function Copy-AllowedTree {
  param(
    [string]$Source,
    [string]$Destination,
    [string[]]$Patterns = @("*")
  )

  if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
    throw "Allowlisted source directory is missing: $Source"
  }
  Assert-NoReparseTree -Root $Source | Out-Null
  Assert-NoReparsePath -Path $Destination | Out-Null
  foreach ($File in @(Get-ChildItem -LiteralPath $Source -Recurse -File | Sort-Object FullName)) {
    $PatternMatched = $false
    foreach ($Pattern in $Patterns) {
      if ($File.Name -like $Pattern) {
        $PatternMatched = $true
        break
      }
    }
    if (-not $PatternMatched) { continue }
    $Relative = Get-RelativePath -Base $Source -Path $File.FullName
    $Target = Join-Path $Destination $Relative.Replace("/", "\")
    Copy-PlainFile -SourceRoot $Source -Source $File.FullName -DestinationRoot $Destination -Destination $Target
  }
}

function Assert-ExactWheelhouse {
  param([string]$Path, [object[]]$Entries)

  Assert-NoReparseTree -Root $Path | Out-Null
  $Expected = @($Entries | ForEach-Object { [string]$_.name } | Sort-Object)
  $Actual = @(
    Get-ChildItem -LiteralPath $Path -File -Filter "*.whl" -ErrorAction SilentlyContinue |
      ForEach-Object { $_.Name } |
      Sort-Object
  )
  if (($Expected -join "`n") -cne ($Actual -join "`n")) {
    throw "Wheel cache must be the exact nine-file locked set"
  }
  foreach ($Entry in $Entries) {
    $WheelPath = Get-SafeContainedPath -Root $Path -Path (Join-Path $Path ([string]$Entry.name))
    Assert-LockedFile -Path $WheelPath -Entry $Entry
  }
}

function Get-LockedWheels {
  param([object[]]$Entries, [string]$RequirementsPath)

  $CachedWheels = @(Get-ChildItem -LiteralPath $CacheDir -File -Filter "*.whl" -ErrorAction SilentlyContinue)
  $CacheReady = $false
  if ($CachedWheels.Count -eq $Entries.Count) {
    try {
      Assert-ExactWheelhouse -Path $CacheDir -Entries $Entries
      $CacheReady = $true
    }
    catch {
      if ($OfflineCacheOnly) { throw }
    }
  }
  elseif ($CachedWheels.Count -gt 0 -and $OfflineCacheOnly) {
    throw "OfflineCacheOnly: wheel cache is not the exact nine-file locked set"
  }
  if ($CacheReady) { return }
  if ($OfflineCacheOnly) {
    throw "OfflineCacheOnly: locked wheel cache is missing"
  }

  $WheelDownload = Get-SafeContainedPath -Root $CacheDir -Path (Join-Path $CacheDir ".wheel-download.partial")
  Remove-SafeTree -Path $WheelDownload
  New-Item -ItemType Directory -Path $WheelDownload -Force | Out-Null
  try {
    & python -m pip download --disable-pip-version-check --only-binary=:all: --platform win_amd64 --python-version 312 --implementation cp --abi cp312 --dest $WheelDownload -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) { throw "pip download failed with exit code $LASTEXITCODE" }
    Assert-ExactWheelhouse -Path $WheelDownload -Entries $Entries

    foreach ($OldWheel in @(Get-ChildItem -LiteralPath $CacheDir -File -Filter "*.whl" -ErrorAction SilentlyContinue)) {
      Remove-SafeFile -Path $OldWheel.FullName
    }
    foreach ($Entry in $Entries) {
      $Downloaded = Get-SafeContainedPath -Root $WheelDownload -Path (Join-Path $WheelDownload ([string]$Entry.name))
      $Partial = Get-SafeContainedPath -Root $CacheDir -Path (Join-Path $CacheDir (([string]$Entry.name) + ".partial"))
      $Final = Get-SafeContainedPath -Root $CacheDir -Path (Join-Path $CacheDir ([string]$Entry.name))
      if (Test-Path -LiteralPath $Final) { throw "Locked wheel cache target already exists: $Final" }
      Remove-SafeFile -Path $Partial
      Copy-PlainFile -SourceRoot $WheelDownload -Source $Downloaded -DestinationRoot $CacheDir -Destination $Partial
      Assert-LockedFile -Path $Partial -Entry $Entry
      Move-Item -LiteralPath $Partial -Destination $Final
    }
    Assert-ExactWheelhouse -Path $CacheDir -Entries $Entries
  }
  catch {
    foreach ($FailedWheel in @(Get-ChildItem -LiteralPath $CacheDir -File -Filter "*.whl.partial" -ErrorAction SilentlyContinue)) {
      Remove-SafeFile -Path $FailedWheel.FullName
    }
    throw
  }
  finally {
    Remove-SafeTree -Path $WheelDownload
  }
}

function Get-DistributionMetadata {
  param([string]$DistInfo)

  $MetadataPath = Join-Path $DistInfo "METADATA"
  if (-not (Test-Path -LiteralPath $MetadataPath -PathType Leaf)) {
    throw "Installed distribution has no METADATA: $DistInfo"
  }
  $MetadataLines = [IO.File]::ReadAllLines($MetadataPath, [Text.Encoding]::UTF8)
  $NameLine = $MetadataLines | Where-Object { $_ -like "Name: *" } | Select-Object -First 1
  $VersionLine = $MetadataLines | Where-Object { $_ -like "Version: *" } | Select-Object -First 1
  if (-not $NameLine -or -not $VersionLine) {
    throw "Installed distribution metadata is incomplete: $DistInfo"
  }
  return [ordered]@{
    name = $NameLine.Substring(6).Trim()
    version = $VersionLine.Substring(9).Trim()
  }
}

function New-DeterministicZip {
  param([string]$SourceRoot, [string]$ZipPath)

  Assert-NoReparseTree -Root $SourceRoot | Out-Null
  $ZipPath = Assert-NoReparsePath -Path $ZipPath
  Add-Type -AssemblyName System.IO.Compression
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $Stream = [IO.File]::Open($ZipPath, [IO.FileMode]::CreateNew)
  try {
    $Archive = New-Object IO.Compression.ZipArchive($Stream, [IO.Compression.ZipArchiveMode]::Create, $false)
    try {
      [string[]]$RelativePaths = @(
        Get-ChildItem -LiteralPath $SourceRoot -Recurse -File |
          ForEach-Object { Get-RelativePath -Base $SourceRoot -Path $_.FullName }
      )
      [Array]::Sort($RelativePaths, [StringComparer]::Ordinal)
      foreach ($Relative in $RelativePaths) {
        $FilePath = Join-Path $SourceRoot $Relative.Replace("/", "\")
        $EntryName = "$PackageDirectoryName/$Relative"
        $Entry = $Archive.CreateEntry($EntryName, [IO.Compression.CompressionLevel]::Optimal)
        $Entry.LastWriteTime = $FixedTimestamp
        $Input = [IO.File]::OpenRead($FilePath)
        $Output = $Entry.Open()
        try { $Input.CopyTo($Output) }
        finally {
          $Output.Dispose()
          $Input.Dispose()
        }
      }
    }
    finally { $Archive.Dispose() }
  }
  finally { $Stream.Dispose() }
}

$RepositoryRoot = Assert-NoReparsePath -Path $RepositoryRoot
if (-not (Test-Path -LiteralPath $RepositoryRoot -PathType Container)) {
  throw "Repository root does not exist: $RepositoryRoot"
}
$LockPath = Get-SafeContainedPath -Root $RepositoryRoot -Path $LockPath
if (-not (Test-Path -LiteralPath $LockPath -PathType Leaf)) {
  throw "Supply lock does not exist: $LockPath"
}
$RequirementsPath = Get-SafeContainedPath -Root $RepositoryRoot -Path (Join-Path $RepositoryRoot "packaging\requirements-offline.lock")
if (-not (Test-Path -LiteralPath $RequirementsPath -PathType Leaf)) { throw "Offline requirements lock is missing" }

$PreviousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$env:PYTHONPATH = Get-SafeContainedPath -Root $RepositoryRoot -Path (Join-Path $RepositoryRoot "src")
$env:UMI_SUPPLY_LOCK = $LockPath
$env:UMI_REQUIREMENTS_LOCK = $RequirementsPath
try {
  $ValidatedLockJson = & python -c "import json,os; from umi_web_spike.package_integrity import load_supply_lock,validate_offline_requirements; value=load_supply_lock(os.environ['UMI_SUPPLY_LOCK']); validate_offline_requirements(value,os.environ['UMI_REQUIREMENTS_LOCK']); print(json.dumps(value,separators=(',',':')))"
  if ($LASTEXITCODE -ne 0) { throw "strict supply lock validation failed with exit code $LASTEXITCODE" }
}
finally {
  Remove-Item Env:UMI_SUPPLY_LOCK -ErrorAction SilentlyContinue
  Remove-Item Env:UMI_REQUIREMENTS_LOCK -ErrorAction SilentlyContinue
  if ($null -eq $PreviousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
  else { $env:PYTHONPATH = $PreviousPythonPath }
}
$Lock = $ValidatedLockJson | ConvertFrom-Json

$CacheDir = Assert-NoReparsePath -Path $CacheDir
$OutputDir = Assert-NoReparsePath -Path $OutputDir
if ($CacheDir -eq $OutputDir) { throw "CacheDir and OutputDir must be distinct" }
$CachePrefix = $CacheDir.TrimEnd("\") + "\"
$OutputPrefix = $OutputDir.TrimEnd("\") + "\"
if ($CacheDir.StartsWith($OutputPrefix, [StringComparison]::OrdinalIgnoreCase) -or $OutputDir.StartsWith($CachePrefix, [StringComparison]::OrdinalIgnoreCase)) {
  throw "CacheDir and OutputDir must not contain one another"
}
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
Assert-NoReparseTree -Root $CacheDir | Out-Null
Assert-NoReparsePath -Path $OutputDir | Out-Null
$UmiAsset = Get-LockedAsset -Entry $Lock.umi
$PythonAsset = Get-LockedAsset -Entry $Lock.python
Get-LockedWheels -Entries @($Lock.wheels) -RequirementsPath $RequirementsPath

$BuildRoot = Get-SafeContainedPath -Root $OutputDir -Path (Join-Path $OutputDir ".offline-package-build")
$ReleaseRoot = Get-SafeContainedPath -Root $BuildRoot -Path (Join-Path $BuildRoot $PackageDirectoryName)
$ZipPath = Get-SafeContainedPath -Root $OutputDir -Path (Join-Path $OutputDir $ExpectedArchiveName)
$ZipPartial = Get-SafeContainedPath -Root $OutputDir -Path "$ZipPath.partial"
$ZipHashPath = Get-SafeContainedPath -Root $OutputDir -Path "$ZipPath.sha256"
$DistSbom = Get-SafeContainedPath -Root $OutputDir -Path (Join-Path $OutputDir "sbom.json")
$DistNotices = Get-SafeContainedPath -Root $OutputDir -Path (Join-Path $OutputDir "THIRD_PARTY_NOTICES.txt")
Remove-SafeTree -Path $BuildRoot
foreach ($OldOutput in @($ZipPath, $ZipPartial, $ZipHashPath, $DistSbom, $DistNotices)) {
  Remove-SafeFile -Path $OldOutput
}

try {
  New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
  Assert-NoReparsePath -Path $ReleaseRoot | Out-Null
  $RuntimeRoot = Get-SafeContainedPath -Root $ReleaseRoot -Path (Join-Path $ReleaseRoot "runtime\python")
  Expand-Archive -LiteralPath $PythonAsset -DestinationPath $RuntimeRoot -Force
  Assert-NoReparseTree -Root $RuntimeRoot | Out-Null
  $SitePackages = Get-SafeContainedPath -Root $RuntimeRoot -Path (Join-Path $RuntimeRoot "Lib\site-packages")
  New-Item -ItemType Directory -Path $SitePackages -Force | Out-Null
  $Pth = @(
    "python312.zip"
    "."
    "Lib"
    "Lib\site-packages"
    "..\..\toolkit\src"
    "import site"
  ) -join "`r`n"
  [IO.File]::WriteAllText((Join-Path $RuntimeRoot "python312._pth"), $Pth + "`r`n", [Text.Encoding]::ASCII)

  & python -m pip install --disable-pip-version-check --no-compile --no-index --find-links $CacheDir --target $SitePackages -r $RequirementsPath
  if ($LASTEXITCODE -ne 0) { throw "offline pip install failed with exit code $LASTEXITCODE" }
  Assert-NoReparseTree -Root $RuntimeRoot | Out-Null
  $DistInfos = @(Get-ChildItem -LiteralPath $SitePackages -Directory -Filter "*.dist-info" | Sort-Object Name)
  if ($DistInfos.Count -ne 9) {
    throw "Portable runtime must contain exactly nine installed distributions"
  }

  $Toolkit = Join-Path $ReleaseRoot "toolkit"
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "src") -Destination (Join-Path $Toolkit "src") -Patterns @("*.py")
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "tests") -Destination (Join-Path $Toolkit "tests") -Patterns @("*.py")
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "scripts\phase0") -Destination (Join-Path $Toolkit "scripts\phase0") -Patterns @("*.ps1", "*.psm1")
  Copy-PlainFile -SourceRoot $RepositoryRoot -Source (Join-Path $RepositoryRoot "scripts\run-windows-validation.ps1") -DestinationRoot $Toolkit -Destination (Join-Path $Toolkit "scripts\run-windows-validation.ps1")
  Copy-PlainFile -SourceRoot $RepositoryRoot -Source (Join-Path $RepositoryRoot "scripts\build-offline-package.ps1") -DestinationRoot $Toolkit -Destination (Join-Path $Toolkit "scripts\build-offline-package.ps1")
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "templates") -Destination (Join-Path $Toolkit "templates") -Patterns @("*.json")
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "packaging") -Destination (Join-Path $Toolkit "packaging") -Patterns @("*.json", "*.lock", "*.txt")
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "docs\validation") -Destination (Join-Path $Toolkit "docs\validation") -Patterns @("*.md")
  $WorkflowSource = Join-Path $RepositoryRoot ".github\workflows"
  if (Test-Path -LiteralPath $WorkflowSource -PathType Container) {
    Copy-AllowedTree -Source $WorkflowSource -Destination (Join-Path $Toolkit ".github\workflows") -Patterns @("*.yml", "*.yaml")
  }
  Copy-PlainFile -SourceRoot $RepositoryRoot -Source (Join-Path $RepositoryRoot "pyproject.toml") -DestinationRoot $Toolkit -Destination (Join-Path $Toolkit "pyproject.toml")

  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "templates") -Destination (Join-Path $ReleaseRoot "templates") -Patterns @("*.json")
  foreach ($EntryName in @("Start-Phase0Validation.ps1", "Phase0.Package.psm1", "Phase0.Scheduler.psm1")) {
    Copy-PlainFile -SourceRoot $RepositoryRoot -Source (Join-Path $RepositoryRoot "scripts\phase0\$EntryName") -DestinationRoot $ReleaseRoot -Destination (Join-Path $ReleaseRoot $EntryName)
  }
  Copy-PlainFile -SourceRoot $RepositoryRoot -Source (Join-Path $RepositoryRoot "docs\validation\offline-package-runbook.md") -DestinationRoot $ReleaseRoot -Destination (Join-Path $ReleaseRoot $OnsiteReadmeName)

  $VendorDir = Join-Path $ReleaseRoot "vendor"
  New-Item -ItemType Directory -Path $VendorDir -Force | Out-Null
  $PackagedUmi = Join-Path $VendorDir ([string]$Lock.umi.name)
  Copy-PlainFile -SourceRoot $CacheDir -Source $UmiAsset -DestinationRoot $ReleaseRoot -Destination $PackagedUmi
  Assert-LockedFile -Path $PackagedUmi -Entry $Lock.umi

  $LicensesRoot = Join-Path $ReleaseRoot "licenses"
  New-Item -ItemType Directory -Path $LicensesRoot -Force | Out-Null
  Copy-PlainFile -SourceRoot $RepositoryRoot -Source (Join-Path $RepositoryRoot "packaging\licenses\Umi-OCR-MIT.txt") -DestinationRoot $ReleaseRoot -Destination (Join-Path $LicensesRoot "Umi-OCR-MIT.txt")
  $PythonLicense = Join-Path $RuntimeRoot "LICENSE.txt"
  if (-not (Test-Path -LiteralPath $PythonLicense -PathType Leaf)) { throw "CPython LICENSE.txt is missing" }
  Copy-PlainFile -SourceRoot $RuntimeRoot -Source $PythonLicense -DestinationRoot $ReleaseRoot -Destination (Join-Path $LicensesRoot "Python.txt")

  $Components = New-Object System.Collections.ArrayList
  [void]$Components.Add([ordered]@{
    name = "Umi-OCR Rapid"; version = "2.1.5"; source_url = [string]$Lock.umi.url
    sha256 = [string]$Lock.umi.sha256; license_files = @("licenses/Umi-OCR-MIT.txt")
  })
  [void]$Components.Add([ordered]@{
    name = "CPython"; version = "3.12.10"; source_url = [string]$Lock.python.url
    sha256 = [string]$Lock.python.sha256; license_files = @("licenses/Python.txt")
  })
  $NoticeLines = New-Object System.Collections.ArrayList
  [void]$NoticeLines.Add("Third-party notices for Umi-OCR Phase 0 offline validation package v0.2.0")
  [void]$NoticeLines.Add("")
  [void]$NoticeLines.Add("===== Umi-OCR Rapid 2.1.5: Umi-OCR-MIT.txt =====")
  [void]$NoticeLines.Add([IO.File]::ReadAllText((Join-Path $LicensesRoot "Umi-OCR-MIT.txt"), [Text.Encoding]::UTF8))
  [void]$NoticeLines.Add("")
  [void]$NoticeLines.Add("===== CPython 3.12.10: Python.txt =====")
  [void]$NoticeLines.Add([IO.File]::ReadAllText((Join-Path $LicensesRoot "Python.txt"), [Text.Encoding]::UTF8))
  [void]$NoticeLines.Add("")

  $LockedWheelByKey = @{}
  foreach ($WheelEntry in @($Lock.wheels)) {
    $WheelParts = ([string]$WheelEntry.name).Split("-")
    if ($WheelParts.Count -lt 5) { throw "Malformed locked wheel filename: $($WheelEntry.name)" }
    $WheelDistribution = ($WheelParts[0].ToLowerInvariant() -replace "[-_.]+", "_")
    $WheelVersion = $WheelParts[1]
    $WheelKey = "$WheelDistribution|$WheelVersion"
    if ($LockedWheelByKey.ContainsKey($WheelKey)) { throw "Duplicate locked wheel distribution/version: $WheelKey" }
    $LockedWheelByKey[$WheelKey] = $WheelEntry
  }
  if ($LockedWheelByKey.Count -ne 9) { throw "Locked wheel map must contain exactly nine unique distributions" }
  $UsedWheelKeys = @{}

  foreach ($DistInfo in $DistInfos) {
    Assert-NoReparseTree -Root $DistInfo.FullName | Out-Null
    $Metadata = Get-DistributionMetadata -DistInfo $DistInfo.FullName
    $NormalizedName = (([string]$Metadata.name).ToLowerInvariant() -replace "[-_.]+", "_")
    $DistributionKey = "$NormalizedName|$($Metadata.version)"
    if (-not $LockedWheelByKey.ContainsKey($DistributionKey)) {
      throw "Installed distribution name/version is not locked: $($Metadata.name) $($Metadata.version)"
    }
    if ($UsedWheelKeys.ContainsKey($DistributionKey)) {
      throw "Locked wheel was mapped more than once: $DistributionKey"
    }
    $WheelEntry = $LockedWheelByKey[$DistributionKey]
    $UsedWheelKeys[$DistributionKey] = $true
    $LicenseFiles = @(
      Get-ChildItem -LiteralPath $DistInfo.FullName -Recurse -File |
        Where-Object { $_.Name -like "LICENSE*" -or $_.Name -like "COPYING*" } |
        Sort-Object FullName
    )
    if ($LicenseFiles.Count -eq 0) {
      throw "Installed distribution has no LICENSE or COPYING file: $($Metadata.name)"
    }
    $LicensePaths = New-Object System.Collections.ArrayList
    foreach ($LicenseFile in $LicenseFiles) {
      $RelativeLicense = Get-RelativePath -Base $DistInfo.FullName -Path $LicenseFile.FullName
      $TargetRelative = "licenses/python/$($DistInfo.Name)/$RelativeLicense"
      $Target = Join-Path $ReleaseRoot $TargetRelative.Replace("/", "\")
      Copy-PlainFile -SourceRoot $DistInfo.FullName -Source $LicenseFile.FullName -DestinationRoot $ReleaseRoot -Destination $Target
      [void]$LicensePaths.Add($TargetRelative)
      [void]$NoticeLines.Add("===== $($Metadata.name) $($Metadata.version): $RelativeLicense =====")
      [void]$NoticeLines.Add([IO.File]::ReadAllText($LicenseFile.FullName, [Text.Encoding]::UTF8))
      [void]$NoticeLines.Add("")
    }
    [void]$Components.Add([ordered]@{
      name = [string]$Metadata.name; version = [string]$Metadata.version
      source_url = "https://pypi.org/project/$($Metadata.name)/$($Metadata.version)/"
      sha256 = [string]$WheelEntry.sha256; license_files = @($LicensePaths)
    })
  }
  if ($UsedWheelKeys.Count -ne $LockedWheelByKey.Count) {
    throw "Every locked wheel must map to exactly one installed distribution"
  }

  $NoticesPath = Join-Path $LicensesRoot "THIRD_PARTY_NOTICES.txt"
  [IO.File]::WriteAllText($NoticesPath, (($NoticeLines -join "`r`n").TrimEnd() + "`r`n"), (New-Object Text.UTF8Encoding($false)))
  $Sbom = [ordered]@{
    schema_version = "1.0"
    tool_version = "0.2.0"
    components = @($Components)
  }
  $SbomPath = Join-Path $ReleaseRoot "sbom.json"
  [IO.File]::WriteAllText($SbomPath, (($Sbom | ConvertTo-Json -Depth 8) + "`r`n"), (New-Object Text.UTF8Encoding($false)))

  $RuntimePython = Join-Path $RuntimeRoot "python.exe"
  if (-not (Test-Path -LiteralPath $RuntimePython -PathType Leaf)) { throw "Portable python.exe is missing" }
  Push-Location $Toolkit
  $PreviousDontWriteBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
  try {
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & $RuntimePython -m pytest tests -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "portable runtime self-test failed with exit code $LASTEXITCODE" }
  }
  finally {
    if ($null -eq $PreviousDontWriteBytecode) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue }
    else { $env:PYTHONDONTWRITEBYTECODE = $PreviousDontWriteBytecode }
    Pop-Location
  }
  $GeneratedCaches = @(
    Get-ChildItem -LiteralPath $ReleaseRoot -Recurse -Force |
      Where-Object { $_.Name -eq "__pycache__" -or $_.Name -eq ".pytest_cache" -or $_.Name -like "*.pyc" }
  )
  if ($GeneratedCaches.Count -ne 0) { throw "Portable self-test left generated cache files in the release tree" }
  Assert-NoReparseTree -Root $ReleaseRoot | Out-Null

  [string[]]$ReleaseRelativePaths = @(
    Get-ChildItem -LiteralPath $ReleaseRoot -Recurse -File |
      ForEach-Object { Get-RelativePath -Base $ReleaseRoot -Path $_.FullName }
  )
  [Array]::Sort($ReleaseRelativePaths, [StringComparer]::Ordinal)
  $ManifestFiles = New-Object System.Collections.ArrayList
  foreach ($Relative in $ReleaseRelativePaths) {
    if ($Relative -in @("manifest.json", "SHA256SUMS.txt")) { continue }
    $File = Get-Item -LiteralPath (Join-Path $ReleaseRoot $Relative.Replace("/", "\"))
    [void]$ManifestFiles.Add([ordered]@{
      path = $Relative
      size = [int64]$File.Length
      sha256 = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    })
  }
  $Manifest = [ordered]@{
    schema_version = "1.0"; tool_version = "0.2.0"; umi_version = "2.1.5"; engine = "RapidOCR"
    files = @($ManifestFiles)
  }
  $ManifestPath = Join-Path $ReleaseRoot "manifest.json"
  [IO.File]::WriteAllText($ManifestPath, (($Manifest | ConvertTo-Json -Depth 6) + "`r`n"), (New-Object Text.UTF8Encoding($false)))
  Assert-NoReparseTree -Root $ReleaseRoot | Out-Null

  $SumsPath = Join-Path $ReleaseRoot "SHA256SUMS.txt"
  [string[]]$SumRelativePaths = @(
    Get-ChildItem -LiteralPath $ReleaseRoot -Recurse -File |
      Where-Object { $_.FullName -cne $SumsPath } |
      ForEach-Object { Get-RelativePath -Base $ReleaseRoot -Path $_.FullName }
  )
  [Array]::Sort($SumRelativePaths, [StringComparer]::Ordinal)
  $SumLines = @(
    foreach ($Relative in $SumRelativePaths) {
      $SumFile = Join-Path $ReleaseRoot $Relative.Replace("/", "\")
      "$((Get-FileHash -LiteralPath $SumFile -Algorithm SHA256).Hash.ToLowerInvariant())  $Relative"
    }
  )
  [IO.File]::WriteAllText($SumsPath, (($SumLines -join "`r`n") + "`r`n"), (New-Object Text.UTF8Encoding($false)))
  Assert-NoReparseTree -Root $ReleaseRoot | Out-Null

  $env:UMI_PACKAGE_VERIFY_ROOT = $ReleaseRoot
  try {
    & $RuntimePython -B -c "import os; from umi_web_spike.package_integrity import verify_package_manifest; verify_package_manifest(os.environ['UMI_PACKAGE_VERIFY_ROOT'])"
    if ($LASTEXITCODE -ne 0) { throw "generated manifest verification failed with exit code $LASTEXITCODE" }
  }
  finally { Remove-Item Env:UMI_PACKAGE_VERIFY_ROOT -ErrorAction SilentlyContinue }

  foreach ($File in @(Get-ChildItem -LiteralPath $ReleaseRoot -Recurse -File)) {
    $File.LastWriteTimeUtc = $FixedTimestamp.UtcDateTime
  }
  New-DeterministicZip -SourceRoot $ReleaseRoot -ZipPath $ZipPartial
  Move-Item -LiteralPath $ZipPartial -Destination $ZipPath
  Assert-NoReparsePath -Path $ZipPath | Out-Null
  $ZipDigest = (Get-FileHash -Algorithm SHA256 $ZipPath).Hash.ToLowerInvariant()
  [IO.File]::WriteAllText($ZipHashPath, "$ZipDigest  $ExpectedArchiveName`r`n", (New-Object Text.UTF8Encoding($false)))
  Copy-PlainFile -SourceRoot $ReleaseRoot -Source $SbomPath -DestinationRoot $OutputDir -Destination $DistSbom
  Copy-PlainFile -SourceRoot $ReleaseRoot -Source $NoticesPath -DestinationRoot $OutputDir -Destination $DistNotices
}
catch {
  foreach ($FailedOutput in @($ZipPath, $ZipPartial, $ZipHashPath, $DistSbom, $DistNotices)) {
    Remove-SafeFile -Path $FailedOutput
  }
  throw
}
finally {
  Remove-SafeTree -Path $BuildRoot
}

Write-Host "Built and verified offline package: $ZipPath"
