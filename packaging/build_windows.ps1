# 打 Windows onedir → dist/albn-autofish\
# 须在 Windows 上运行。可选环境变量：PYTHON
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if ($env:PYTHON) {
  $Py = $env:PYTHON
} elseif (Test-Path "$Root\.venv\Scripts\python.exe") {
  $Py = "$Root\.venv\Scripts\python.exe"
} else {
  $Py = (Get-Command python).Source
}

Write-Host "Using: $Py"
& $Py -m pip install -q -r "$Root\requirements.txt" "pyinstaller>=6.0,<7"
& $Py -m PyInstaller --noconfirm --clean `
  --distpath "$Root\dist" `
  --workpath "$Root\build\pyinstaller" `
  "$Root\packaging\albn_autofish_windows.spec"

Write-Host "输出: $Root\dist\albn-autofish\"
