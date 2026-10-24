# forge-backend 镜像（docs/16 T1.82）：纯 API 服务端，无浏览器依赖——
# C2 执行器不挂服务器（create_app 纯 API 形态），patchright 仅作为 forge-trace 的库依赖装入
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY packages/proto/python /srv/pkg/proto
COPY packages/block-sdk/python /srv/pkg/block-sdk
COPY packages/trace/python /srv/pkg/trace
COPY packages/certifier/python /srv/pkg/certifier
COPY apps/server /srv/app

RUN pip install --no-cache-dir \
      /srv/pkg/proto /srv/pkg/block-sdk /srv/pkg/trace /srv/pkg/certifier \
      '/srv/app[pg]'

# 固定 UID：与 /opt/aim/forge/data 卷属主对齐（SERVER_STEPS §3）
RUN useradd --system --uid 8100 --create-home forge
USER forge

EXPOSE 8041
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8041/healthz', timeout=3)"]
CMD ["python", "-m", "forge_server"]
