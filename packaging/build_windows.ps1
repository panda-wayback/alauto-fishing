# 打 Windows onedir → dist\albn-autofish-<后缀>\
# 可选环境变量：PYTHON、ALBN_BUILD_SUFFIX
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Invoke-Checked {
  param([string]$Exe, [string[]]$Arguments)
  & $Exe @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "command failed ($LASTEXITCODE): $Exe $($Arguments -join ' ')"
  }
}

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
Invoke-Checked $Py @("-m", "pip", "install", "-q", "-r", "$Root\requirements.txt", "pyinstaller>=6.0,<7")
Invoke-Checked $Py @("$Root\packaging\write_expire.py")

# 同名重打时 PyInstaller 会删掉目标目录；若其中有用户 data\ 则先挪走再放回
$Out = Join-Path $Root "dist\$($env:ALBN_DIST_NAME)"
$DataDir = Join-Path $Out "data"
$DataBak = Join-Path $Root "build\data_backup_$($env:ALBN_BUILD_SUFFIX)"
if (Test-Path $DataBak) {
  Write-Error "leftover backup $DataBak — resolve manually before rebuild"
  exit 1
}
if (Test-Path $DataDir) {
  New-Item -ItemType Directory -Force -Path (Join-Path $Root "build") | Out-Null
  Move-Item -LiteralPath $DataDir -Destination $DataBak
}

try {
  Invoke-Checked $Py @(
    "-m", "PyInstaller", "--noconfirm", "--clean",
    "--distpath", "$Root\dist",
    "--workpath", "$Root\build\pyinstaller",
    "$Root\packaging\albn_autofish_windows.spec"
  )
} finally {
  if (Test-Path $DataBak) {
    New-Item -ItemType Directory -Force -Path $Out | Out-Null
    if (Test-Path $DataDir) { Remove-Item -LiteralPath $DataDir -Recurse -Force }
    Move-Item -LiteralPath $DataBak -Destination $DataDir
    Write-Host "restored user data: $DataDir"
  }
}

Set-Content -Path (Join-Path $Root "dist\.build_suffix") -Value $env:ALBN_BUILD_SUFFIX -NoNewline
Set-Content -Path (Join-Path $Root "dist\.build_windows_name") -Value $env:ALBN_DIST_NAME -NoNewline
Write-Host "out: $Out\"
