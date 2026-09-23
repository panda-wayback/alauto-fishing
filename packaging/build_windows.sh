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

# PyInstaller 会整个删掉 dist/albn-autofish/，其中 data/ 是用户数据：打包前移走、结束后放回
DATA_DIR="$ROOT/dist/albn-autofish/data"
DATA_BAK="$ROOT/build/data_backup"
restore_data() {
  if [[ -d "$DATA_BAK" ]]; then
    mkdir -p "$ROOT/dist/albn-autofish"
    rm -rf "$DATA_DIR"
    mv "$DATA_BAK" "$DATA_DIR"
    echo "已恢复用户数据: $DATA_DIR"
  fi
}
if [[ -d "$DATA_BAK" ]]; then
  echo "发现上次未恢复的备份 $DATA_BAK，请先手动处理后再打包" >&2
  exit 1
fi
if [[ -d "$DATA_DIR" ]]; then
  mkdir -p "$ROOT/build"
  mv "$DATA_DIR" "$DATA_BAK"
fi
trap restore_data EXIT

"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build/pyinstaller" \
  "$ROOT/packaging/albn_autofish_windows.spec"

echo "输出: $ROOT/dist/albn-autofish/"
