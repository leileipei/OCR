[CmdletBinding(DefaultParameterSetName = 'Direct')]
param(
  [Parameter(Mandatory=$true, ParameterSetName='ArgumentFile')][string]$ArgumentFile,
  [Parameter(ParameterSetName='Direct')][string]$ProjectRoot = '',
  [Parameter(Mandatory=$true, ParameterSetName='Direct')][string]$UmiDataRoot,
  [Parameter(Mandatory=$true, ParameterSetName='Direct')][string]$TestPythonExe,
  [Parameter(Mandatory=$true, ParameterSetName='Direct')][string]$PythonExe,
  [Parameter(Mandatory=$true, ParameterSetName='Direct')][string]$PluginRoot,
  [Parameter(Mandatory=$true, ParameterSetName='Direct')][string]$PluginName,
  [Parameter(Mandatory=$true, ParameterSetName='Direct')][string]$GlobalOptions,
  [Parameter(Mandatory=$true, ParameterSetName='Direct')][string]$LocalOptions,
  [Parameter(Mandatory=$true, ParameterSetName='Direct')][string]$SamplesManifest,
  [Parameter(ParameterSetName='Direct')][string]$ValidationId = ([guid]::NewGuid().ToString('N')),
  [Parameter(Mandatory=$true, ParameterSetName='Direct')][string]$CampaignId,
  [Parameter(Mandatory=$true, ParameterSetName='Direct')][int]$Attempt,
  [Parameter(Mandatory=$true, ParameterSetName='Direct')]
  [ValidateSet('Interactive', 'Scheduled')][string]$ExecutionMode,
  [Parameter(ParameterSetName='Direct')][string]$OutputDir = '',
  [Parameter(ParameterSetName='Direct')][string]$StdoutLog = '',
  [Parameter(ParameterSetName='Direct')][string]$StderrLog = '',
  [Parameter(ParameterSetName='Direct')][int]$MinPages = 100,
  [Parameter(ParameterSetName='Direct')][int]$BusinessConcurrencyLimit = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$parent = [System.IO.Path]::GetDirectoryName($PSScriptRoot)
$PackageRoot = if ([System.IO.Path]::GetFileName($parent) -eq 'toolkit') {
  [System.IO.Path]::GetDirectoryName($parent)
} else { $parent }
$PackageRoot = [System.IO.Path]::GetFullPath($PackageRoot)
$schedulerModule = Join-Path $PackageRoot 'Phase0.Scheduler.psm1'
if (-not (Test-Path -LiteralPath $schedulerModule -PathType Leaf)) {
  $schedulerModule = Join-Path $PackageRoot 'scripts/phase0/Phase0.Scheduler.psm1'
}
Import-Module $schedulerModule -Force

function Assert-Phase0RunnerArguments {
  param($Values)
  $validated = Assert-Phase0RunnerConfiguration -PackageRoot $PackageRoot -Configuration $Values
  return $validated
}

if ($PSCmdlet.ParameterSetName -eq 'ArgumentFile') {
  $configuration = Read-Phase0TrustedRunnerArguments -PackageRoot $PackageRoot -ArgumentFile $ArgumentFile
}
else {
  if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = if (Test-Path -LiteralPath (Join-Path $PackageRoot 'toolkit/src')) {
      Join-Path $PackageRoot 'toolkit'
    } else { $PackageRoot }
  }
  $attemptName = 'attempt-{0:D4}' -f $Attempt
  $attemptRoot = Join-Path $PackageRoot "work/campaigns/$CampaignId/attempts/$attemptName"
  if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $attemptRoot ("ocr/" + $ExecutionMode.ToLowerInvariant() + "/$ValidationId")
  }
  $configuration = [pscustomobject][ordered]@{
    package_root = $PackageRoot; project_root = $ProjectRoot; umi_data_root = $UmiDataRoot
    test_python_exe = $TestPythonExe; python_exe = $PythonExe; plugin_root = $PluginRoot; plugin_name = $PluginName
    global_options = $GlobalOptions; local_options = $LocalOptions; samples_manifest = $SamplesManifest
    validation_id = $ValidationId; campaign_id = $CampaignId; execution_mode = $ExecutionMode; output_dir = $OutputDir
    min_pages = $MinPages; business_concurrency_limit = $BusinessConcurrencyLimit
    stdout_log = $StdoutLog; stderr_log = $StderrLog; attempt = $Attempt
  }
  $null = Assert-Phase0RunnerArguments -Values $configuration
}

$ProjectRoot = [string]$configuration.project_root
$UmiDataRoot = [string]$configuration.umi_data_root
$TestPythonExe = [string]$configuration.test_python_exe
$PythonExe = [string]$configuration.python_exe
$PluginRoot = [string]$configuration.plugin_root
$PluginName = [string]$configuration.plugin_name
$GlobalOptions = [string]$configuration.global_options
$LocalOptions = [string]$configuration.local_options
$SamplesManifest = [string]$configuration.samples_manifest
$ValidationId = [string]$configuration.validation_id
$CampaignId = [string]$configuration.campaign_id
$ExecutionMode = [string]$configuration.execution_mode
$OutputDir = [string]$configuration.output_dir
$MinPages = [int]$configuration.min_pages
$BusinessConcurrencyLimit = [int]$configuration.business_concurrency_limit
$StdoutLog = [string]$configuration.stdout_log
$StderrLog = [string]$configuration.stderr_log

$UseLogs = -not [string]::IsNullOrWhiteSpace($StdoutLog) -and -not [string]::IsNullOrWhiteSpace($StderrLog)
if ($UseLogs) {
  if ($StdoutLog -eq $StderrLog) { throw 'Standard output and error logs must be different' }
  foreach ($logPath in @($StdoutLog, $StderrLog)) {
    if (Test-Path -LiteralPath $logPath) { throw "Refusing to overwrite validation log: $logPath" }
  }
  foreach ($logPath in @($StdoutLog, $StderrLog)) {
    $stream = New-Object System.IO.FileStream(
      $logPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read
    )
    $stream.Dispose()
  }
}
elseif (-not [string]::IsNullOrWhiteSpace($StdoutLog) -or -not [string]::IsNullOrWhiteSpace($StderrLog)) {
  throw 'Standard output and error logs must be configured together'
}

function Invoke-Phase0Native {
  param([string]$Executable, [string[]]$Arguments)
  $exitCode = Invoke-Phase0NativeProcess -Executable $Executable -Arguments $Arguments -StdoutLog $StdoutLog -StderrLog $StderrLog
  return [int]$exitCode
}

$ExitCode = 1
$OriginalPythonPath = $env:PYTHONPATH
Push-Location $ProjectRoot
try {
  $env:PYTHONPATH = "$ProjectRoot\src"
  $ExitCode = Invoke-Phase0Native -Executable $TestPythonExe -Arguments @('-m', 'pytest', '-q')
  if ($ExitCode -eq 0) {
    $env:PYTHONPATH = "$ProjectRoot\src;$UmiDataRoot\py_src\imports;$UmiDataRoot\site-packages"
    $ExitCode = Invoke-Phase0Native -Executable $PythonExe -Arguments @(
      '-m', 'umi_web_spike.cli', 'validate-ocr',
      '--validation-id', $ValidationId,
      '--campaign-id', $CampaignId,
      '--plugin-root', $PluginRoot,
      '--plugin-name', $PluginName,
      '--global-options-json', $GlobalOptions,
      '--local-options-json', $LocalOptions,
      '--samples-manifest', $SamplesManifest,
      '--output-dir', $OutputDir,
      '--execution-mode', $ExecutionMode.ToLowerInvariant(),
      '--min-pages', [string]$MinPages,
      '--business-concurrency-limit', [string]$BusinessConcurrencyLimit
    )
  }
}
finally {
  $env:PYTHONPATH = $OriginalPythonPath
  Pop-Location
}
exit $ExitCode
