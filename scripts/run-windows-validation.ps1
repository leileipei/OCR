param(
  [string]$ProjectRoot = (Resolve-Path ".").Path,
  [Parameter(Mandatory=$true)][string]$UmiDataRoot,
  [Parameter(Mandatory=$true)][string]$PythonExe,
  [Parameter(Mandatory=$true)][string]$PluginRoot,
  [Parameter(Mandatory=$true)][string]$PluginName,
  [Parameter(Mandatory=$true)][string]$GlobalOptions,
  [Parameter(Mandatory=$true)][string]$LocalOptions,
  [Parameter(Mandatory=$true)][string]$Image,
  [Parameter(Mandatory=$true)][string]$Pdf
)

$ErrorActionPreference = "Stop"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$env:PYTHONPATH = "$ProjectRoot\src;$UmiDataRoot\py_src\imports;$UmiDataRoot\site-packages"
& $PythonExe -m umi_web_spike.cli validate-ocr `
  --plugin-root $PluginRoot `
  --plugin-name $PluginName `
  --global-options-json $GlobalOptions `
  --local-options-json $LocalOptions `
  --image $Image `
  --pdf $Pdf `
  --output-dir validation/results/live
exit $LASTEXITCODE
