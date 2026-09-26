# 打 Windows onedir → dist\albn-autofish-<后缀>\
# 可选环境变量：PYTHON、ALBN_BUILD_SUFFIX
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if ($env:PYTHON) {
  $Py = $env:PYTHON
} elseif (Test-Path "$Root\.venv\Scripts\python.exe") {
  $Py = "$Root\.venv\Scripts\python.exe"
} elseif (Test-Path "$Root\.conda\python.exe") {
  $Py = "$Root\.conda\python.exe"
} else {
  $Py = (Get-Command python).Source
}

if (-not $env:ALBN_BUILD_SUFFIX) {
  if ($env:GITHUB_RUN_ID) {
    $env:ALBN_BUILD_SUFFIX = $env:GITHUB_RUN_ID
  } else {
    $env:ALBN_BUILD_SUFFIX = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
  }
}
$env:ALBN_DIST_NAME = "albn-autofish-$($env:ALBN_BUILD_SUFFIX)"

Write-Host "Using: $Py"
Write-Host "Dist: $($env:ALBN_DIST_NAME)  suffix=$($env:ALBN_BUILD_SUFFIX)"
& $Py -m pip install -q -r "$Root\requirements.txt" "pyinstaller>=6.0,<7"
& $Py "$Root\packaging\write_expire.py"
& $Py -m PyInstaller --noconfirm --clean `
  --distpath "$Root\dist" `
  --workpath "$Root\build\pyinstaller" `
  "$Root\packaging\albn_autofish_windows.spec"

$Out = Join-Path $Root "dist\$($env:ALBN_DIST_NAME)"
Set-Content -Path (Join-Path $Root "dist\.build_suffix") -Value $env:ALBN_BUILD_SUFFIX -NoNewline
Set-Content -Path (Join-Path $Root "dist\.build_windows_name") -Value $env:ALBN_DIST_NAME -NoNewline
Write-Host "输出: $Out\"
