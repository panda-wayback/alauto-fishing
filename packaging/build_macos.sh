#!/usr/bin/env bash
# 打 macOS .app → dist/albn-autofish.app
# 可选环境变量：PYTHON=/path/to/python
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

echo "Using: $PY"
echo "Bundle: ${ALBN_BUNDLE_ID:-com.albn.autofish}  App: ${ALBN_APP_NAME:-albn-autofish.app}"
"$PY" -m pip install -q -r "$ROOT/requirements.txt" "pyinstaller>=6.0,<7"
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build/pyinstaller" \
  "$ROOT/packaging/albn_autofish.spec"

OUT_APP="${ALBN_APP_NAME:-albn-autofish.app}"
[[ "$OUT_APP" == *.app ]] || OUT_APP="${OUT_APP}.app"
echo "输出: $ROOT/dist/$OUT_APP"
