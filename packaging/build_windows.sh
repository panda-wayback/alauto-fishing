#!/usr/bin/env bash
# 打 Windows onedir → dist/albn-autofish-<后缀>/
# 须在 Windows 上运行。可选：PYTHON=  ALBN_BUILD_SUFFIX=
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

if [[ -z "${ALBN_BUILD_SUFFIX:-}" ]]; then
  if [[ -n "${GITHUB_RUN_ID:-}" ]]; then
    ALBN_BUILD_SUFFIX="${GITHUB_RUN_ID}"
  else
    ALBN_BUILD_SUFFIX="$(date -u +%Y%m%d-%H%M%S)"
  fi
fi
export ALBN_BUILD_SUFFIX
export ALBN_DIST_NAME="albn-autofish-${ALBN_BUILD_SUFFIX}"

echo "Using: $PY"
echo "Dist: $ALBN_DIST_NAME  suffix=$ALBN_BUILD_SUFFIX"
"$PY" -m pip install -q -r "$ROOT/requirements.txt" "pyinstaller>=6.0,<7"
# 壳包不需要模拟器：打包前卸掉，避免捞进产物；结束后随 data 一并恢复环境
"$PY" -m pip uninstall -y pygame 2>/dev/null || true

# 同名重打时 PyInstaller 会删掉目标目录；若其中有用户 data/ 则先挪走再放回
DATA_DIR="$ROOT/dist/${ALBN_DIST_NAME}/data"
DATA_BAK="$ROOT/build/data_backup_${ALBN_BUILD_SUFFIX}"
restore_after() {
  if [[ -d "$DATA_BAK" ]]; then
    mkdir -p "$ROOT/dist/${ALBN_DIST_NAME}"
    rm -rf "$DATA_DIR"
    mv "$DATA_BAK" "$DATA_DIR"
    echo "已恢复用户数据: $DATA_DIR"
  fi
  "$PY" -m pip install -q 'pygame>=2.6.0,<3' 2>/dev/null || true
}
if [[ -d "$DATA_BAK" ]]; then
  echo "发现上次未恢复的备份 $DATA_BAK，请先手动处理后再打包" >&2
  exit 1
fi
if [[ -d "$DATA_DIR" ]]; then
  mkdir -p "$ROOT/build"
  mv "$DATA_DIR" "$DATA_BAK"
fi
trap restore_after EXIT

"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build/pyinstaller" \
  "$ROOT/packaging/albn_autofish_windows.spec"

OUT="$ROOT/dist/${ALBN_DIST_NAME}"
if [[ -d "$OUT" ]]; then
  bash "$ROOT/packaging/trim_bundle.sh" "$OUT"
fi
printf '%s\n' "$ALBN_BUILD_SUFFIX" >"$ROOT/dist/.build_suffix"
printf '%s\n' "$ALBN_DIST_NAME" >"$ROOT/dist/.build_windows_name"
echo "输出: $OUT/"
if [[ -d "$OUT" ]]; then
  du -sh "$OUT" 2>/dev/null || powershell.exe -NoProfile -Command \
    "(Get-ChildItem -LiteralPath '$OUT' -Recurse -File | Measure-Object Length -Sum).Sum / 1MB"
fi
