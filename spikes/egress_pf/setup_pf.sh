#!/bin/bash
# setup_pf.sh — 建专用用户并装载 PF anchor 规则（未实测，待 macOS 硬件）
# 用法: ./setup_pf.sh <proxy_port>
# 纪律: 第一步即备份 PF 规则；每条命令回显；任何失败立即退出并提示恢复命令。
set -euo pipefail

PORT="${1:?usage: setup_pf.sh <proxy_port>}"
DIR="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$DIR/pf_rules_backup-$STAMP.txt"

echo "== 0) 备份当前 PF 规则到 $BACKUP"
sudo pfctl -s rules | tee "$BACKUP"

echo "== 1) 建专用用户 _forge_comp（隐藏、不可登录）"
if dscl . -read /Users/_forge_comp >/dev/null 2>&1; then
  echo "   已存在，跳过创建"
else
  sudo dscl . -create /Users/_forge_comp
  sudo dscl . -create /Users/_forge_comp UserShell /usr/bin/false
  sudo dscl . -create /Users/_forge_comp RealName "Forge spike component user"
  sudo dscl . -create /Users/_forge_comp UniqueID 499
  sudo dscl . -create /Users/_forge_comp PrimaryGroupID 20
  sudo dscl . -create /Users/_forge_comp NFSHomeDirectory /var/forge-comp
  sudo dscl . -create /Users/_forge_comp IsHidden 1
  sudo mkdir -p /var/forge-comp
  sudo chown _forge_comp /var/forge-comp
fi

echo "== 2) 装载 anchor 规则（forge-spike：出站默认阻断，仅放行 loopback）"
sudo pfctl -a forge-spike -f "$DIR/com.forge-spike.pf.conf"

echo "== 3) 确认 PF 已启用（如未启用则启用）"
sudo pfctl -E 2>/dev/null || true

echo "== 4) 校验规则在场"
sudo pfctl -a forge-spike -s rules

echo "== 完成。记得结束时运行 ./teardown_pf.sh；恢复备份: sudo pfctl -f $BACKUP 对应的全局规则只在改动主规则集时需要"
