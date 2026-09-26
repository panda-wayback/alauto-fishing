#!/usr/bin/env bash
# 打完包后删掉漏打的 Qt / pygame 等（macOS .app 与 Windows onedir 共用）。
# 用法：bash packaging/trim_bundle.sh <产物根目录>
set -euo pipefail

ROOT="${1:-}"
if [[ -z "$ROOT" || ! -d "$ROOT" ]]; then
  echo "用法: $0 <bundle-root>" >&2
  exit 2
fi

# 按名字/路径剔除；-depth 先删深路径
while IFS= read -r -d '' p; do
  rm -rf "$p"
done < <(
  find "$ROOT" -depth \( \
      -iname '*WebEngine*' -o \
      -iname '*Qt3D*' -o \
      -iname '*QtQuick*' -o \
      -iname '*QtQml*' -o \
      -iname '*QtPdf*' -o \
      -iname '*QtVirtualKeyboard*' -o \
      -iname '*VirtualKeyboard*' -o \
      -iname '*QtCharts*' -o \
      -iname '*QtDataVisualization*' -o \
      -iname '*QtMultimedia*' -o \
      -iname '*QtPositioning*' -o \
      -iname '*QtSensors*' -o \
      -iname '*QtSql*' -o \
      -iname '*QtTest*' -o \
      -iname '*QtWebChannel*' -o \
      -iname '*QtWebSockets*' -o \
      -iname '*QtWebView*' -o \
      -iname 'Designer.app' -o \
      -iname 'Linguist.app' -o \
      -iname 'Assistant.app' -o \
      -iname 'pygame' -o \
      -iname 'pygame-*' -o \
      -iname '*SDL2*' -o \
      -iname 'libSDL2*' -o \
      -iname 'libFLAC*' -o \
      -iname 'haarcascade*' \
    \) -print0 2>/dev/null || true
)

echo "trim_bundle: $ROOT"
du -sh "$ROOT" 2>/dev/null || true
