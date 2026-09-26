#!/usr/bin/env bash
# Build macOS keygen .app → dist/albn-license-keygen-<suffix>.app
# Optional: PYTHON=  ALBN_BUILD_SUFFIX=
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

if [[ -z "${ALBN_KEYGEN_APP_NAME:-}" ]]; then
  ALBN_KEYGEN_APP_NAME="albn-license-keygen-${ALBN_BUILD_SUFFIX}.app"
else
  _base="${ALBN_KEYGEN_APP_NAME%.app}"
  case "$_base" in
    *"-${ALBN_BUILD_SUFFIX}") ;;
    *) ALBN_KEYGEN_APP_NAME="${_base}-${ALBN_BUILD_SUFFIX}.app" ;;
  esac
fi
[[ "$ALBN_KEYGEN_APP_NAME" == *.app ]] || ALBN_KEYGEN_APP_NAME="${ALBN_KEYGEN_APP_NAME}.app"
export ALBN_KEYGEN_APP_NAME

echo "Using: $PY"
echo "Bundle: ${ALBN_KEYGEN_BUNDLE_ID:-com.albn.license-keygen}  App: $ALBN_KEYGEN_APP_NAME"
"$PY" -m pip install -q -r "$ROOT/requirements.txt" "pyinstaller>=6.0,<7"
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build/pyinstaller-keygen" \
  "$ROOT/packaging/albn_license_keygen.spec"

APP_PATH="$ROOT/dist/$ALBN_KEYGEN_APP_NAME"
# PyInstaller COLLECT 中间目录，.app 已含内容，可删
rm -rf "$ROOT/dist/albn-license-keygen"
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
  printf '%s\n' "$ALBN_KEYGEN_APP_NAME" >"$ROOT/dist/.build_keygen_macos_name"
  echo "out: $APP_PATH"
  du -sh "$APP_PATH" || true
else
  echo "missing: $APP_PATH" >&2
  exit 1
fi
