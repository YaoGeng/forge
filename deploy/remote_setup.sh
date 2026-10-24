#!/usr/bin/env bash
# forge 服务器侧一次性初始化（docs/16 T1.84；SERVER_STEPS §3-5 实例化）
# 红线：只动 forge 命名空间 + 追加式共享登记（backup.sh/htpasswd/CREDENTIALS/nginx conf.d）
set -euo pipefail

echo "== 1) 目录与数据卷"
sudo mkdir -p /opt/aim/forge/data
sudo chown deploy:deploy /opt/aim/forge
sudo chown -R 8100:8100 /opt/aim/forge/data
cp /tmp/forge_compose.yml /opt/aim/forge/compose.yml

echo "== 2) .env（600）"
DBPW=$(openssl rand -hex 24)
cat > /opt/aim/forge/.env <<EOF
FORGE_DB_URL=postgresql+psycopg://forge_app:${DBPW}@aim-pg:5432/forge
FORGE_HOST=0.0.0.0
FORGE_PORT=8041
FORGE_DATA_DIR=/data
EOF
chmod 600 /opt/aim/forge/.env

echo "== 3) 建库 forge / forge_app（幂等前提：现库清单无 forge）"
docker exec -i aim-pg psql -U postgres <<SQL
CREATE USER forge_app WITH PASSWORD '${DBPW}';
CREATE DATABASE forge OWNER forge_app;
REVOKE ALL PRIVILEGES ON DATABASE forge FROM PUBLIC;
SQL

echo "== 4) Basic Auth 追加用户 forge（不动既有 admin）"
BASICPW=$(openssl rand -hex 16)
HASH=$(openssl passwd -apr1 "$BASICPW")
echo "forge:${HASH}" | sudo tee -a /opt/aim/infra/nginx/conf.d/admin.htpasswd > /dev/null

echo "== 5) nginx forge.conf 装载（仅新增文件 + reload）"
sudo cp /tmp/forge.conf /opt/aim/infra/nginx/conf.d/forge.conf
docker exec aim-nginx nginx -t
docker exec aim-nginx nginx -s reload

echo "== 6) backup.sh 清单追加 forge（先备份原件）"
cp /opt/aim/scripts/backup.sh /opt/aim/scripts/backup.sh.bak_forge_20261025
sed -i 's/for DB in ljr zfk lmz;/for DB in ljr zfk lmz forge;/g' /opt/aim/scripts/backup.sh
grep -n "for DB" /opt/aim/scripts/backup.sh

echo "== 7) CREDENTIALS.md 登记（600）"
sudo bash -c "cat >> /opt/aim/infra/CREDENTIALS.md <<EOF

## forge（2026-10-25 上线）
- DB：forge / forge_app，密码：${DBPW}（连接串见 /opt/aim/forge/.env）
- Basic Auth：用户 forge，密码：${BASICPW}（nginx admin.htpasswd 追加；admin 用户为既有产品共用不动）
EOF"
sudo chmod 600 /opt/aim/infra/CREDENTIALS.md

echo "== 8) 回源预检（容器未起，预期 502 = resolver 寻址正常）"
curl -sk -u "forge:${BASICPW}" -H "Host: forge.aim8848.com" -o /dev/null -w "origin=%{http_code}\n" https://127.0.0.1/

echo "SETUP_DONE BASIC=forge:${BASICPW}"
