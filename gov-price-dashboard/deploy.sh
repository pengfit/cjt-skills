#!/usr/bin/env bash
# gov-price-dashboard · 本地部署脚本
# ----------------------------------------------------------------------------
# 用法:
#   ./deploy.sh build              # 仅构建镜像
#   ./deploy.sh deploy             # 本地拉取 + 重启容器
#   ./deploy.sh status             # 查看本地容器/镜像状态
#   ./deploy.sh rollback [tag]     # 回滚到指定 tag（默认回滚到上一个镜像）
#   ./deploy.sh help               # 查看用法
#
# 环境变量（可选，缺省走默认值）:
#   IMAGE_NAME       镜像名（不带 tag），默认 pengfit/dashboard
#   IMAGE_TAG        镜像 tag，默认 latest
#   CONTAINER_NAME   容器名，默认 gov-price-dashboard
#   HEALTH_HOST_PORT 健康检查访问端口（compose 映射到 host 的端口），默认 8080
#   HEALTH_TIMEOUT   健康检查超时秒数，默认 60
# ----------------------------------------------------------------------------

set -euo pipefail

# ====================== 配置 ======================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
CONTAINER_NAME="${CONTAINER_NAME:-gov-price-dashboard}"

IMAGE_NAME="${IMAGE_NAME:-pengfit/dashboard}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
LOCAL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

# 健康检查（compose 里 8080→5200，5200 没暴露 host）
HEALTH_HOST_PORT="${HEALTH_HOST_PORT:-8080}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-60}"   # 秒

# ====================== 颜色 ======================
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YLW=$'\033[1;33m'; BLU=$'\033[0;34m'; NC=$'\033[0m'
else
    RED=''; GRN=''; YLW=''; BLU=''; NC=''
fi

log()  { echo "${BLU}[deploy]${NC} $*"; }
ok()   { echo "${GRN}[deploy] ✓${NC} $*"; }
warn() { echo "${YLW}[deploy] ⚠${NC} $*"; }
die()  { echo "${RED}[deploy] ✗${NC} $*" >&2; exit 1; }

# ====================== 前置检查 ======================
preflight() {
    command -v docker >/dev/null 2>&1 || die "docker 未安装"
    [[ -f "$COMPOSE_FILE" ]] || die "找不到 docker-compose.yml: $COMPOSE_FILE"
    docker compose version >/dev/null 2>&1 \
        || die "docker compose 不可用（需要 Docker 20.10+）"
}

# ====================== 公共工具 ======================
# 容器当前 health 状态（healthy / starting / unhealthy / <none>）
container_health() {
    docker inspect --format='{{.State.Health.Status}}' "${CONTAINER_NAME}" 2>/dev/null \
        || echo "absent"
}

# 等待容器 health=healthy（依赖 compose 配置 healthcheck）
wait_for_health() {
    local deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
    while (( $(date +%s) < deadline )); do
        local h; h=$(container_health)
        case "$h" in
            healthy)  ok "容器 healthy"; return 0 ;;
            unhealthy) die "容器进入 unhealthy，请查看 docker logs ${CONTAINER_NAME}" ;;
            *)        log "等待 health… 当前=${h}" ;;
        esac
        sleep 2
    done

    # fallback：compose 没配 healthcheck 时，curl 映射到 host 的端口
    warn "compose 未配 healthcheck 或超时，fallback 到 curl http://localhost:${HEALTH_HOST_PORT}/healthz"
    if curl -fsS "http://localhost:${HEALTH_HOST_PORT}/healthz" >/dev/null 2>&1; then
        ok "API 在线（curl /healthz 通过）"
        return 0
    fi
    die "健康检查失败（${HEALTH_TIMEOUT}s 超时），请查看 docker logs ${CONTAINER_NAME}"
}

# ====================== 子命令 ======================
cmd_build() {
    log "构建镜像: ${LOCAL_IMAGE}"
    cd "$WORKSPACE_ROOT"
    docker compose -f "$COMPOSE_FILE" build --no-cache
    ok "构建完成: ${LOCAL_IMAGE}"
}

cmd_deploy() {
    log "重启本地容器（使用 ${LOCAL_IMAGE}）"
    cd "$WORKSPACE_ROOT"
    docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-deps dashboard
    wait_for_health
    ok "服务在线: http://localhost:${HEALTH_HOST_PORT} (容器内 5200)"
}

cmd_status() {
    echo "=== 本地镜像 (${IMAGE_NAME}) ==="
    docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}" \
        --filter "reference=${IMAGE_NAME}" 2>/dev/null \
        | head -20 || true

    echo ""
    echo "=== 容器状态 ==="
    docker ps -a --filter "name=^${CONTAINER_NAME}\$" \
        --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null \
        || true

    echo ""
    echo "=== 健康检查 ==="
    local h; h=$(container_health)
    echo "容器 health: ${h}"
    if curl -fsS "http://localhost:${HEALTH_HOST_PORT}/healthz" >/dev/null 2>&1; then
        ok "API 在线（http://localhost:${HEALTH_HOST_PORT}/healthz）"
        return 0
    else
        warn "API 离线"
        return 1
    fi
}

cmd_rollback() {
    local target="${1:-}"
    if [[ -z "$target" ]]; then
        # 找上一个本地镜像 tag（严格整行排除当前 tag，避免 v1.2.3 误匹配 v1.2.30）
        target=$(docker images --format "{{.Tag}}" "${IMAGE_NAME}" \
                 | grep -vx "${IMAGE_TAG}" \
                 | head -1 || true)
        if [[ -z "$target" ]]; then
            die "没有可回滚的镜像（只有当前 tag: ${IMAGE_TAG}）"
        fi
        warn "未指定 tag，自动选上一个: ${target}"
    fi

    log "回滚到 tag=${target}"
    cd "$WORKSPACE_ROOT"
    IMAGE_TAG="$target" docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-deps dashboard
    wait_for_health
    ok "回滚完成: tag=${target}"
}

cmd_help() {
    sed -n '2,13p' "$0" | sed 's/^# \?//'
}

# ====================== 主入口 ======================
preflight
case "${1:-help}" in
    build)    shift; cmd_build "$@" ;;
    deploy)   shift; cmd_deploy "$@" ;;
    status)   shift; cmd_status "$@" ;;
    rollback) shift; cmd_rollback "$@" ;;
    help|-h|--help) cmd_help ;;
    *) die "未知命令: $1（执行 $0 help 查看用法）" ;;
esac