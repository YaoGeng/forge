#!/bin/bash
# teardown_pf.sh — 卸载 anchor 规则并删除专用用户（未实测，待 macOS 硬件）
# 纪律: 恢复后逐项核验；失败时提示人工对照 pf_rules_backup-*.txt。
set -euo pipefail

echo "== 1) 清空 forge-spike anchor 规则"
sudo pfctl -a forge-spike -F all || echo "!! anchor 清理失败，请人工执行: sudo pfctl -a forge-spike -F all"

echo "== 2) 删除专用用户 _forge_comp"
if dscl . -read /Users/_forge_comp >/dev/null 2>&1; then
  sudo dscl . -delete /Users/_forge_comp
  sudo rm -rf /var/forge-comp
else
  echo "   用户不存在，跳过"
fi

echo "== 3) 核验"
if dscl . -read /Users/_forge_comp >/dev/null 2>&1; then
  echo "!! 用户仍存在，请人工: sudo dscl . -delete /Users/_forge_comp"
  exit 1
fi
echo "== 核验通过（anchor 规则清空、用户已删；全局规则未动过，无需还原）"
