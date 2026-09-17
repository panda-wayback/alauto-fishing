#!/usr/bin/env bash
# 在本机打 macOS 单文件：dist/albn-autofish
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.conda/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="${ROOT}/.venv/bin/python"
fi
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

"$PY" -m pip install -q "pyinstaller>=6.0,<7"
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build/pyinstaller" \
  "$ROOT/packaging/albn_autofish.spec"

echo "输出: $ROOT/dist/albn-autofish.app"
echo "用法: 拷到其它 Mac 双击运行；ROI 存在 ~/Library/Application Support/albn-autofish/。"
echo "首次运行需授权屏幕录制与辅助功能。"
