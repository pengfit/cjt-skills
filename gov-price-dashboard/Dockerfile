# ============ Stage 1: 前端构建 (Node 20) ============
FROM node:20-alpine AS frontend-build

WORKDIR /build/frontend

# 单独 COPY package.json 走 npm ci 缓存
COPY gov-price-dashboard/frontend/package*.json ./
RUN npm ci --no-audit --no-fund

COPY gov-price-dashboard/frontend/ ./
# Vite build → dist/
RUN npm run build

# ============ Stage 2: Python 运行时 (slim) ============
FROM python:3.11-slim AS runtime

LABEL maintainer="pengfit" \
      version="1.0" \
      description="gov-price-dashboard: FastAPI + Vue 3 single-container image"

# 容器内时区
ENV TZ=Asia/Shanghai \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# 系统依赖（curl 健康检查；sqlite3 fastapi 等 wheel 已含）
# 切阿里云镜像（deb.debian.org 国内不稳，常 502）
RUN for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
        [ -f "$f" ] && sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' "$f" || true; \
    done \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖（独立 COPY 走 docker layer 缓存）
COPY gov-price-dashboard/api/requirements.txt .
# pip 切清华源（pypi.org 国内 SSL 不稳）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn \
    && pip install -r requirements.txt

# 后端代码
COPY gov-price-dashboard/api/ ./api/

# 前端构建产物（从前一阶段拷）
COPY --from=frontend-build /build/frontend/dist ./static

# Skills 数据打包进镜像（data/ + 各 skill.yml），实现自包含部署
# build context 为 ..（skills/ 根），通过同根 .dockerignore 过滤 +
# COPY --exclude 排除 gov-price-dashboard/（Dockerfile 要从那里 COPY，但不能复制到 /app/skills/）
COPY --exclude=gov-price-dashboard ./ ./skills/

# 工作目录默认 /app

# 环境变量默认值（生产可被 compose 覆盖）
ENV ES_HOST=http://host.docker.internal:59200 \
    ES_INDEX=dws_xian_price \
    CATEGORY_DB=/app/skills/data/breed_canonical.db \
    SKILLS_ROOT=/app/skills \
    HOST=0.0.0.0 \
    PORT=5200

EXPOSE 5200

# 健康检查（用容器内 localhost，避免反向代理干扰）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:5200/api/health || exit 1

# 启动（多 worker）
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "5200", "--workers", "2", "--proxy-headers"]