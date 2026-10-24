# Forge 上线服务器侧步骤（docs/16 T1.84 命令包）

> 对应《服务器部署标准》§8 十步。标注【用户】= 用户本人操作；【服务器】= 在 aimServer（deploy 账号 SSH）执行，可代做；【CI】= GitHub Actions 自动。

## 1. DNS（【用户】）

Cloudflare 面板新增 A 记录：`forge → 43.160.219.44`，灰云（仅 DNS），TTL 自动。

## 2. GitHub 部署密钥（【用户】）

```bash
ssh-keygen -t ed25519 -f forge-ci-deploy -C "forge-ci-deploy@github-actions" -N ""
# 公钥追加到服务器 /home/deploy/.ssh/authorized_keys（独立一行，吊销=删该行）
# 私钥整文件 → GitHub 仓库 Settings → Secrets → Actions：SERVER_SSH_KEY
# 另配 secrets：SERVER_HOST = deploy@43.160.219.44；FORGE_BASIC = <basic用户:密码>（部署后公网 healthz 断言用）
```

## 3. 产品目录与 .env（【服务器】）

```bash
sudo mkdir -p /opt/aim/forge/data
cd /opt/aim/forge
PW=$(openssl rand -base64 24)
cat > .env <<EOF
FORGE_DB_URL=postgresql+psycopg://forge_app:${PW}@aim-pg:5432/forge
FORGE_HOST=0.0.0.0
FORGE_PORT=8041
FORGE_DATA_DIR=/data
EOF
chmod 600 .env
sudo chown -R 8100:8100 /opt/aim/forge/data
sudo chown deploy:deploy /opt/aim/forge
cp deploy/compose.yml /opt/aim/forge/compose.yml   # 从本仓库 deploy/ 同步（rsync/scp）
echo "forge_app 密码: ${PW}"   # 记入 /opt/aim/infra/CREDENTIALS.md（600）
```

## 4. 建库（【服务器】）

```bash
PW=<与 .env 相同的密码>
docker exec -i aim-pg psql -U postgres <<EOF
CREATE USER forge_app WITH PASSWORD '${PW}';
CREATE DATABASE forge OWNER forge_app;
REVOKE ALL PRIVILEGES ON DATABASE forge FROM PUBLIC;
EOF
```

（表结构由应用启动时 `Base.metadata.create_all` 完成，标准 §7.1 第 3 条的"迁移工具"在 forge v0 即 create_all，Alembic 后置沿用 D-M1E.1 口径。）

## 5. Nginx（【服务器】）

```bash
cp deploy/nginx/forge.conf /opt/aim/infra/nginx/conf.d/forge.conf
# Basic Auth 复用标准 §5.4 的 admin.htpasswd（zfk 同款；如需独立凭据另生成）
docker exec aim-nginx nginx -t && docker exec aim-nginx nginx -s reload
curl -sk -H "Host: forge.aim8848.com" https://127.0.0.1/ -o /dev/null -w "%{http_code}\n"
# 容器未起前预期 502（resolver 寻址，reload 不报错）——这正是注记要的形态
```

## 6. 首次部署（【CI】）

```bash
git tag v0.1.0 && git push origin main --tags   # 触发 .github/workflows/deploy.yml
# 流程：build 镜像 → docker save | ssh load → FORGE_TAG=v0.1.0 compose up -d → healthz 断言
```

## 7. 上线验证清单（【服务器】+ 本地）

- [ ] `docker ps`：forge-backend healthy（内存限 512M）
- [ ] `curl -u <basic用户:密码> https://forge.aim8848.com/healthz` → 200 `{"status":"ok"}`
- [ ] 无 Basic → 401
- [ ] `/docs` → 404（生产关文档）
- [ ] `/creator` → 200
- [ ] `GET /api/v1/apps`（带 Basic）→ 200 空列表
- [ ] `ss -tlnp`：公网仍仅 22/80/443；8041 仅 127.0.0.1
- [ ] 次日 `/opt/aim/backups/forge/` 生成 dump

## 8. 监控与备份登记（【用户】+【服务器】）

- 【用户】UptimeRobot 加 `https://forge.aim8848.com/healthz` HTTPS 探测（5 分钟）——**HTTP Basic 凭据必须一并配置**（全站在 Basic 之后，不带凭据全程 401 误报宕机；终审 M4）
- 【服务器】`/opt/aim/scripts/backup.sh` 的 DB 清单加 `forge`

## 9. 文档回填（【服务器】记录，改动桌面两文档）

- 《数据架构文档》§5.4 表加行：forge / forge_app / 8041
- 《服务器部署标准》§11.2 追加 forge 部署记录、§11.3 版本行
