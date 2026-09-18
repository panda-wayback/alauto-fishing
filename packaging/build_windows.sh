#!/usr/bin/env bash
# 打 Windows onedir → dist/albn-autofish/
# 须在 Windows 上运行。可选：PYTHON=...
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x "${ROOT}/.venv/Scripts/python.exe" ]]; then
  PY="${ROOT}/.venv/Scripts/python.exe"
elif [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
else
  PY="$(command -v python || command -v python3)"
fi

echo "Using: $PY"
"$PY" -m pip install -q -r "$ROOT/requirements.txt" "pyinstaller>=6.0,<7"
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build/pyinstaller" \
  "$ROOT/packaging/albn_autofish_windows.spec"

echo "输出: $ROOT/dist/albn-autofish/"
