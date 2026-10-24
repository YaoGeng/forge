-- forge 库初始化（数据架构文档 §9.1 模板实例化；在 aim-pg 容器内执行）
-- 密码占位：<在服务器上 openssl rand -base64 24 生成后替换，与 /opt/aim/forge/.env 的 FORGE_DB_URL 一致>
CREATE USER forge_app WITH PASSWORD '<OPENSSL_RAND_BASE64_24>';
CREATE DATABASE forge OWNER forge_app;
REVOKE ALL PRIVILEGES ON DATABASE forge FROM PUBLIC;
