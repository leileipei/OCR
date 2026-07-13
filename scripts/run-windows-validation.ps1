param(
  [string]$ProjectRoot = (Resolve-Path ".").Path,
  [Parameter(Mandatory=$true)][string]$UmiDataRoot,
  [Parameter(Mandatory=$true)][string]$TestPythonExe,
  [Parameter(Mandatory=$true)][string]$PythonExe,
  [Parameter(Mandatory=$true)][string]$PluginRoot,
  [Parameter(Mandatory=$true)][string]$PluginName,
  [Parameter(Mandatory=$true)][string]$GlobalOptions,
  [Parameter(Mandatory=$true)][string]$LocalOptions,
  [Parameter(Mandatory=$true)][string]$SamplesManifest,
  [string]$ValidationId = ([guid]::NewGuid().ToString('N')),
  [int]$MinPages = 100
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$RunsRoot = Join-Path $ProjectRoot 'validation\results\runs'
$OutputDir = Join-Path $RunsRoot $ValidationId
$ExitCode = 0
$OriginalPythonPath = $env:PYTHONPATH

Push-Location $ProjectRoot
try {
  $env:PYTHONPATH = "$ProjectRoot\src"
  & $TestPythonExe -m pytest -q
  if ($LASTEXITCODE -ne 0) {
    $ExitCode = $LASTEXITCODE
  } else {
    $env:PYTHONPATH = "$ProjectRoot\src;$UmiDataRoot\py_src\imports;$UmiDataRoot\site-packages"
    & $PythonExe -m umi_web_spike.cli validate-ocr `
      --validation-id $ValidationId `
      --plugin-root $PluginRoot `
      --plugin-name $PluginName `
      --global-options-json $GlobalOptions `
      --local-options-json $LocalOptions `
      --samples-manifest $SamplesManifest `
      --output-dir $OutputDir `
      --min-pages $MinPages
    $ExitCode = $LASTEXITCODE
  }
} finally {
  $env:PYTHONPATH = $OriginalPythonPath
  Pop-Location
}
exit $ExitCode
