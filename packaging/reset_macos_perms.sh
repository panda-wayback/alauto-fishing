#!/usr/bin/env bash
# 清除本应用在 macOS TCC 中的屏幕录制 / 辅助功能记录，便于重打包后重新授权。
# 用法：bash packaging/reset_macos_perms.sh
# 可选：ALBN_BUNDLE_ID=com.albn.autofish.dev bash packaging/reset_macos_perms.sh
set -euo pipefail

IDS=(
  "${ALBN_BUNDLE_ID:-}"
  "com.albn.autofish"
  "com.albn.autofish.dev"
)

# 去重且去掉空
uniq_ids=()
seen=""
for id in "${IDS[@]}"; do
  [[ -z "$id" ]] && continue
  case " $seen " in
    *" $id "*) continue ;;
  esac
  seen+=" $id"
  uniq_ids+=("$id")
done

echo "将清除以下 Bundle ID 的 TCC 记录："
for id in "${uniq_ids[@]}"; do
  echo "  - $id"
done
echo ""

for id in "${uniq_ids[@]}"; do
  for svc in Accessibility ScreenCapture; do
    if tccutil reset "$svc" "$id" 2>/dev/null; then
      echo "OK  tccutil reset $svc $id"
    else
      echo "SKIP tccutil reset $svc $id（可能本机无此记录或需更高权限）"
    fi
  done
done

echo ""
echo "完成。请："
echo "  1) 系统设置 → 隐私与安全性 → 删掉旧的「Albn Autofish」条目（若还在）"
echo "  2) 重新打开 .app，用顶栏「权限」重新授权"
echo "本地反复测包建议：make build-macos-dev  （独立 Bundle ID，不跟正式包抢授权）"
