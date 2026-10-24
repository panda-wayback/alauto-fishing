#!/usr/bin/env bash
# 打 macOS .app → dist/albn-autofish-<后缀>.app
# 可选：PYTHON=  ALBN_BUILD_SUFFIX=（默认：CI 用 GITHUB_RUN_ID，本地用 UTC 时间戳）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -n "${PYTHON:-}" && -x "${PYTHON}" ]]; then
  PY="$PYTHON"
elif [[ -x "${ROOT}/.conda/bin/python" ]]; then
  PY="${ROOT}/.conda/bin/python"
elif [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
else
  PY="$(command -v python3)"
fi

if [[ -z "${ALBN_BUILD_SUFFIX:-}" ]]; then
  if [[ -n "${GITHUB_RUN_ID:-}" ]]; then
    ALBN_BUILD_SUFFIX="${GITHUB_RUN_ID}"
  else
    ALBN_BUILD_SUFFIX="$(date -u +%Y%m%d-%H%M%S)"
  fi
fi
export ALBN_BUILD_SUFFIX

# 未指定 ALBN_APP_NAME → albn-autofish-<后缀>.app
# 已指定（如 build-macos-dev）→ 在 .app 前插入后缀，避免互相覆盖
if [[ -z "${ALBN_APP_NAME:-}" ]]; then
  ALBN_APP_NAME="albn-autofish-${ALBN_BUILD_SUFFIX}.app"
else
  _base="${ALBN_APP_NAME%.app}"
  case "$_base" in
    *"-${ALBN_BUILD_SUFFIX}") ;;
    *) ALBN_APP_NAME="${_base}-${ALBN_BUILD_SUFFIX}.app" ;;
  esac
fi
[[ "$ALBN_APP_NAME" == *.app ]] || ALBN_APP_NAME="${ALBN_APP_NAME}.app"
export ALBN_APP_NAME

echo "Using: $PY"
echo "Bundle: ${ALBN_BUNDLE_ID:-com.albn.autofish}  App: $ALBN_APP_NAME  suffix=$ALBN_BUILD_SUFFIX"
"$PY" -m pip install -q -r "$ROOT/requirements.txt" "pyinstaller>=6.0,<7"
"$PY" "$ROOT/packaging/write_expire.py"
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build/pyinstaller" \
  "$ROOT/packaging/albn_autofish.spec"

OUT_APP="$ALBN_APP_NAME"
APP_PATH="$ROOT/dist/$OUT_APP"

# 兜底：若环境仍残留完整 PySide6，删掉未使用的重量级 Qt 组件
if [[ -d "$APP_PATH" ]]; then
  while IFS= read -r -d '' p; do
    rm -rf "$p"
  done < <(find "$APP_PATH" \( \
      -iname '*WebEngine*' -o \
      -iname '*Qt3D*' -o \
      -iname '*QtQuick*' -o \
      -iname '*QtQml*' -o \
      -iname 'Designer.app' -o \
      -iname 'Linguist.app' -o \
      -iname 'Assistant.app' \
    \) -print0 2>/dev/null || true)
  # 供 CI 读取
  printf '%s\n' "$ALBN_BUILD_SUFFIX" >"$ROOT/dist/.build_suffix"
  printf '%s\n' "$OUT_APP" >"$ROOT/dist/.build_macos_name"
  echo "输出: $APP_PATH"
  du -sh "$APP_PATH" || true
  echo "--- 体积 Top（Frameworks / MacOS）---"
  du -sh "$APP_PATH/Contents/Frameworks"/* 2>/dev/null | sort -hr | head -n 20 || true
else
  echo "输出缺失: $APP_PATH" >&2
  exit 1
fi
