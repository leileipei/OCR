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

function Assert-LockedFile {
  param([string]$Path, [object]$Entry)

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

  $FinalPath = Join-Path $CacheDir ([string]$Entry.name)
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

  $PartialPath = "$FinalPath.partial"
  Remove-Item -LiteralPath $PartialPath -Force -ErrorAction SilentlyContinue
  try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri ([string]$Entry.url) -OutFile $PartialPath -UseBasicParsing
    Assert-LockedFile -Path $PartialPath -Entry $Entry
    Move-Item -LiteralPath $PartialPath -Destination $FinalPath
    Assert-LockedFile -Path $FinalPath -Entry $Entry
    return $FinalPath
  }
  catch {
    Remove-Item -LiteralPath $PartialPath -Force -ErrorAction SilentlyContinue
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
    New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
    Copy-Item -LiteralPath $File.FullName -Destination $Target
  }
}

function Assert-ExactWheelhouse {
  param([string]$Path, [object[]]$Entries)

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
    Assert-LockedFile -Path (Join-Path $Path ([string]$Entry.name)) -Entry $Entry
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

  $WheelDownload = Join-Path $CacheDir ".wheel-download.partial"
  Remove-Item -LiteralPath $WheelDownload -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Path $WheelDownload -Force | Out-Null
  try {
    & python -m pip download --disable-pip-version-check --only-binary=:all: --platform win_amd64 --python-version 312 --implementation cp --abi cp312 --dest $WheelDownload -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) { throw "pip download failed with exit code $LASTEXITCODE" }
    Assert-ExactWheelhouse -Path $WheelDownload -Entries $Entries

    foreach ($OldWheel in @(Get-ChildItem -LiteralPath $CacheDir -File -Filter "*.whl" -ErrorAction SilentlyContinue)) {
      Remove-Item -LiteralPath $OldWheel.FullName -Force
    }
    foreach ($Entry in $Entries) {
      $Downloaded = Join-Path $WheelDownload ([string]$Entry.name)
      $Partial = Join-Path $CacheDir (([string]$Entry.name) + ".partial")
      $Final = Join-Path $CacheDir ([string]$Entry.name)
      Copy-Item -LiteralPath $Downloaded -Destination $Partial
      Assert-LockedFile -Path $Partial -Entry $Entry
      Move-Item -LiteralPath $Partial -Destination $Final
    }
    Assert-ExactWheelhouse -Path $CacheDir -Entries $Entries
  }
  catch {
    Get-ChildItem -LiteralPath $CacheDir -File -Filter "*.whl.partial" -ErrorAction SilentlyContinue |
      Remove-Item -Force -ErrorAction SilentlyContinue
    throw
  }
  finally {
    Remove-Item -LiteralPath $WheelDownload -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function Get-DistributionMetadata {
  param([string]$DistInfo)

  $MetadataPath = Join-Path $DistInfo "METADATA"
  if (-not (Test-Path -LiteralPath $MetadataPath -PathType Leaf)) {
    throw "Installed distribution has no METADATA: $DistInfo"
  }
  $NameLine = Get-Content -LiteralPath $MetadataPath | Where-Object { $_ -like "Name: *" } | Select-Object -First 1
  $VersionLine = Get-Content -LiteralPath $MetadataPath | Where-Object { $_ -like "Version: *" } | Select-Object -First 1
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

if (-not (Test-Path -LiteralPath $LockPath -PathType Leaf)) {
  throw "Supply lock does not exist: $LockPath"
}
$Lock = Get-Content -LiteralPath $LockPath -Raw | ConvertFrom-Json
if ([string]$Lock.schema_version -cne "1.0" -or [string]$Lock.tool_version -cne "0.2.0") {
  throw "Unsupported offline-package.lock.json schema or tool version"
}
if ([string]$Lock.archive_name -cne $ExpectedArchiveName) {
  throw "Archive name is not the locked release name"
}
if (@($Lock.wheels).Count -ne 9) {
  throw "Supply lock must contain exactly nine wheels"
}

New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$RequirementsPath = Join-Path $RepositoryRoot "packaging\requirements-offline.lock"
$UmiAsset = Get-LockedAsset -Entry $Lock.umi
$PythonAsset = Get-LockedAsset -Entry $Lock.python
Get-LockedWheels -Entries @($Lock.wheels) -RequirementsPath $RequirementsPath

$BuildRoot = Join-Path $OutputDir ".offline-package-build"
$ReleaseRoot = Join-Path $BuildRoot $PackageDirectoryName
$ZipPath = Join-Path $OutputDir $ExpectedArchiveName
$ZipPartial = "$ZipPath.partial"
$ZipHashPath = "$ZipPath.sha256"
$DistSbom = Join-Path $OutputDir "sbom.json"
$DistNotices = Join-Path $OutputDir "THIRD_PARTY_NOTICES.txt"
Remove-Item -LiteralPath $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
foreach ($OldOutput in @($ZipPath, $ZipPartial, $ZipHashPath, $DistSbom, $DistNotices)) {
  Remove-Item -LiteralPath $OldOutput -Force -ErrorAction SilentlyContinue
}

try {
  New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
  $RuntimeRoot = Join-Path $ReleaseRoot "runtime\python"
  Expand-Archive -LiteralPath $PythonAsset -DestinationPath $RuntimeRoot -Force
  $SitePackages = Join-Path $RuntimeRoot "Lib\site-packages"
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
  $DistInfos = @(Get-ChildItem -LiteralPath $SitePackages -Directory -Filter "*.dist-info" | Sort-Object Name)
  if ($DistInfos.Count -ne 9) {
    throw "Portable runtime must contain exactly nine installed distributions"
  }

  $Toolkit = Join-Path $ReleaseRoot "toolkit"
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "src") -Destination (Join-Path $Toolkit "src") -Patterns @("*.py")
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "tests") -Destination (Join-Path $Toolkit "tests") -Patterns @("*.py")
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "scripts\phase0") -Destination (Join-Path $Toolkit "scripts\phase0") -Patterns @("*.ps1", "*.psm1")
  Copy-Item -LiteralPath (Join-Path $RepositoryRoot "scripts\run-windows-validation.ps1") -Destination (Join-Path $Toolkit "scripts\run-windows-validation.ps1") -Force
  Copy-Item -LiteralPath (Join-Path $RepositoryRoot "scripts\build-offline-package.ps1") -Destination (Join-Path $Toolkit "scripts\build-offline-package.ps1") -Force
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "templates") -Destination (Join-Path $Toolkit "templates") -Patterns @("*.json")
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "packaging") -Destination (Join-Path $Toolkit "packaging") -Patterns @("*.json", "*.lock", "*.txt")
  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "docs\validation") -Destination (Join-Path $Toolkit "docs\validation") -Patterns @("*.md")
  $WorkflowSource = Join-Path $RepositoryRoot ".github\workflows"
  if (Test-Path -LiteralPath $WorkflowSource -PathType Container) {
    Copy-AllowedTree -Source $WorkflowSource -Destination (Join-Path $Toolkit ".github\workflows") -Patterns @("*.yml", "*.yaml")
  }
  Copy-Item -LiteralPath (Join-Path $RepositoryRoot "pyproject.toml") -Destination (Join-Path $Toolkit "pyproject.toml")

  Copy-AllowedTree -Source (Join-Path $RepositoryRoot "templates") -Destination (Join-Path $ReleaseRoot "templates") -Patterns @("*.json")
  foreach ($EntryName in @("Start-Phase0Validation.ps1", "Phase0.Package.psm1", "Phase0.Scheduler.psm1")) {
    Copy-Item -LiteralPath (Join-Path $RepositoryRoot "scripts\phase0\$EntryName") -Destination (Join-Path $ReleaseRoot $EntryName)
  }
  Copy-Item -LiteralPath (Join-Path $RepositoryRoot "docs\validation\offline-package-runbook.md") -Destination (Join-Path $ReleaseRoot "README-现场验证.md")

  $VendorDir = Join-Path $ReleaseRoot "vendor"
  New-Item -ItemType Directory -Path $VendorDir -Force | Out-Null
  $PackagedUmi = Join-Path $VendorDir ([string]$Lock.umi.name)
  Copy-Item -LiteralPath $UmiAsset -Destination $PackagedUmi
  Assert-LockedFile -Path $PackagedUmi -Entry $Lock.umi

  $LicensesRoot = Join-Path $ReleaseRoot "licenses"
  New-Item -ItemType Directory -Path $LicensesRoot -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $RepositoryRoot "packaging\licenses\Umi-OCR-MIT.txt") -Destination (Join-Path $LicensesRoot "Umi-OCR-MIT.txt")
  $PythonLicense = Join-Path $RuntimeRoot "LICENSE.txt"
  if (-not (Test-Path -LiteralPath $PythonLicense -PathType Leaf)) { throw "CPython LICENSE.txt is missing" }
  Copy-Item -LiteralPath $PythonLicense -Destination (Join-Path $LicensesRoot "Python.txt")

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
  [void]$NoticeLines.Add((Get-Content -LiteralPath (Join-Path $LicensesRoot "Umi-OCR-MIT.txt") -Raw))
  [void]$NoticeLines.Add("")
  [void]$NoticeLines.Add("===== CPython 3.12.10: Python.txt =====")
  [void]$NoticeLines.Add((Get-Content -LiteralPath (Join-Path $LicensesRoot "Python.txt") -Raw))
  [void]$NoticeLines.Add("")

  foreach ($DistInfo in $DistInfos) {
    $Metadata = Get-DistributionMetadata -DistInfo $DistInfo.FullName
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
      New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
      Copy-Item -LiteralPath $LicenseFile.FullName -Destination $Target
      [void]$LicensePaths.Add($TargetRelative)
      [void]$NoticeLines.Add("===== $($Metadata.name) $($Metadata.version): $RelativeLicense =====")
      [void]$NoticeLines.Add((Get-Content -LiteralPath $LicenseFile.FullName -Raw))
      [void]$NoticeLines.Add("")
    }
    $NormalizedName = ([string]$Metadata.name).ToLowerInvariant().Replace("-", "_")
    $WheelEntry = @($Lock.wheels | Where-Object { ([string]$_.name).ToLowerInvariant().Replace("-", "_").StartsWith($NormalizedName + "_") -or ([string]$_.name).ToLowerInvariant().Replace("-", "_").StartsWith($NormalizedName + "-") }) | Select-Object -First 1
    if (-not $WheelEntry) {
      $WheelEntry = @($Lock.wheels | Where-Object { ([string]$_.name).ToLowerInvariant().StartsWith(([string]$Metadata.name).ToLowerInvariant() + "-") }) | Select-Object -First 1
    }
    if (-not $WheelEntry) { throw "No locked wheel matches installed distribution: $($Metadata.name)" }
    [void]$Components.Add([ordered]@{
      name = [string]$Metadata.name; version = [string]$Metadata.version
      source_url = "https://pypi.org/project/$($Metadata.name)/$($Metadata.version)/"
      sha256 = [string]$WheelEntry.sha256; license_files = @($LicensePaths)
    })
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
  $ZipDigest = (Get-FileHash -Algorithm SHA256 $ZipPath).Hash.ToLowerInvariant()
  [IO.File]::WriteAllText($ZipHashPath, "$ZipDigest  $ExpectedArchiveName`r`n", (New-Object Text.UTF8Encoding($false)))
  Copy-Item -LiteralPath $SbomPath -Destination $DistSbom
  Copy-Item -LiteralPath $NoticesPath -Destination $DistNotices
}
catch {
  foreach ($FailedOutput in @($ZipPath, $ZipPartial, $ZipHashPath, $DistSbom, $DistNotices)) {
    Remove-Item -LiteralPath $FailedOutput -Force -ErrorAction SilentlyContinue
  }
  throw
}
finally {
  Remove-Item -LiteralPath $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Built and verified offline package: $ZipPath"
