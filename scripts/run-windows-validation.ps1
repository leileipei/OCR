[CmdletBinding(DefaultParameterSetName = 'Direct')]
param(
  [Parameter(Mandatory=$true, ParameterSetName='ArgumentFile')][string]$ArgumentFile,
  [Parameter(ParameterSetName='Direct')][string]$ProjectRoot = (Resolve-Path ".").Path,
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
  [Parameter(Mandatory=$true, ParameterSetName='Direct')]
  [ValidateSet('Interactive', 'Scheduled')][string]$ExecutionMode,
  [Parameter(ParameterSetName='Direct')][string]$OutputDir = '',
  [Parameter(ParameterSetName='Direct')][string]$StdoutLog = '',
  [Parameter(ParameterSetName='Direct')][string]$StderrLog = '',
  [Parameter(ParameterSetName='Direct')][int]$MinPages = 100,
  [Parameter(ParameterSetName='Direct')][int]$BusinessConcurrencyLimit = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-Phase0RunnerArguments {
  param($Values)
  $required = @(
    'project_root', 'umi_data_root', 'test_python_exe', 'python_exe', 'plugin_root', 'plugin_name',
    'global_options', 'local_options', 'samples_manifest', 'validation_id', 'campaign_id',
    'execution_mode', 'output_dir', 'min_pages', 'business_concurrency_limit', 'stdout_log', 'stderr_log'
  )
  $actual = @($Values.PSObject.Properties.Name | Sort-Object)
  if (@(Compare-Object ($required | Sort-Object) $actual).Count -ne 0) {
    throw 'Scheduled argument file contains unexpected or missing fields'
  }
  foreach ($name in @('validation_id', 'campaign_id')) {
    if ([string]$Values.$name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
      throw "Invalid scheduled argument identifier: $name"
    }
  }
  if ($Values.validation_id -eq $Values.campaign_id) { throw 'ValidationId and CampaignId must be different' }
  if ([string]$Values.execution_mode -notin @('Interactive', 'Scheduled')) { throw 'Invalid execution mode' }
  if ([int]$Values.min_pages -lt 1 -or [int]$Values.business_concurrency_limit -lt 1) { throw 'Validation limits must be positive' }
  $hasStdout = -not [string]::IsNullOrWhiteSpace([string]$Values.stdout_log)
  $hasStderr = -not [string]::IsNullOrWhiteSpace([string]$Values.stderr_log)
  if ($hasStdout -ne $hasStderr) { throw 'Standard output and error logs must be configured together' }
}

if ($PSCmdlet.ParameterSetName -eq 'ArgumentFile') {
  $ArgumentFile = (Resolve-Path -LiteralPath $ArgumentFile).Path
  $argumentValues = [System.IO.File]::ReadAllText($ArgumentFile, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  Assert-Phase0RunnerArguments -Values $argumentValues
  $ProjectRoot = [string]$argumentValues.project_root
  $UmiDataRoot = [string]$argumentValues.umi_data_root
  $TestPythonExe = [string]$argumentValues.test_python_exe
  $PythonExe = [string]$argumentValues.python_exe
  $PluginRoot = [string]$argumentValues.plugin_root
  $PluginName = [string]$argumentValues.plugin_name
  $GlobalOptions = [string]$argumentValues.global_options
  $LocalOptions = [string]$argumentValues.local_options
  $SamplesManifest = [string]$argumentValues.samples_manifest
  $ValidationId = [string]$argumentValues.validation_id
  $CampaignId = [string]$argumentValues.campaign_id
  $ExecutionMode = [string]$argumentValues.execution_mode
  $OutputDir = [string]$argumentValues.output_dir
  $MinPages = [int]$argumentValues.min_pages
  $BusinessConcurrencyLimit = [int]$argumentValues.business_concurrency_limit
  $StdoutLog = [string]$argumentValues.stdout_log
  $StderrLog = [string]$argumentValues.stderr_log
}
else {
  $directValues = [pscustomobject]@{
    project_root = $ProjectRoot; umi_data_root = $UmiDataRoot; test_python_exe = $TestPythonExe
    python_exe = $PythonExe; plugin_root = $PluginRoot; plugin_name = $PluginName; global_options = $GlobalOptions
    local_options = $LocalOptions; samples_manifest = $SamplesManifest; validation_id = $ValidationId
    campaign_id = $CampaignId; execution_mode = $ExecutionMode; output_dir = $OutputDir
    min_pages = $MinPages; business_concurrency_limit = $BusinessConcurrencyLimit
    stdout_log = $StdoutLog; stderr_log = $StderrLog
  }
  Assert-Phase0RunnerArguments -Values $directValues
}

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$RunsRoot = Join-Path $ProjectRoot 'validation\results\runs'
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
  $ModeRoot = Join-Path $RunsRoot ($ExecutionMode.ToLowerInvariant())
  $OutputDir = Join-Path $ModeRoot $ValidationId
}
if ($ExecutionMode -eq 'Interactive' -and $OutputDir -match '[\\/]scheduled[\\/]') {
  throw 'Interactive and scheduled validation output directories must be different'
}
if ($ExecutionMode -eq 'Scheduled' -and $OutputDir -match '[\\/]interactive[\\/]') {
  throw 'Interactive and scheduled validation output directories must be different'
}
$ExitCode = 0
$OriginalPythonPath = $env:PYTHONPATH
$UseLogs = -not [string]::IsNullOrWhiteSpace($StdoutLog) -and -not [string]::IsNullOrWhiteSpace($StderrLog)
if ($UseLogs) {
  if ($StdoutLog -eq $StderrLog) { throw 'Standard output and error logs must be different' }
  foreach ($logPath in @($StdoutLog, $StderrLog)) {
    if (Test-Path -LiteralPath $logPath) { throw "Refusing to overwrite validation log: $logPath" }
  }
  foreach ($logPath in @($StdoutLog, $StderrLog)) {
    $fullLogPath = [System.IO.Path]::GetFullPath($logPath)
    $parent = [System.IO.Path]::GetDirectoryName($fullLogPath)
    $null = [System.IO.Directory]::CreateDirectory($parent)
    $stream = New-Object System.IO.FileStream($fullLogPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    $stream.Dispose()
  }
}

function Invoke-Phase0Native {
  param([string]$Executable, [string[]]$Arguments)
  if ($UseLogs) {
    & $Executable @Arguments 1>> $StdoutLog 2>> $StderrLog
  }
  else {
    & $Executable @Arguments
  }
  return [int]$LASTEXITCODE
}

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
