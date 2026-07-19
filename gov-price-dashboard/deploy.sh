#!/usr/bin/env bash
# gov-price-dashboard · 自动部署脚本
# ----------------------------------------------------------------------------
# 用法:
#   ./deploy.sh build              # 仅构建镜像（不推送）
#   ./deploy.sh publish            # 构建 + tag + push 到阿里云 ACR
#   ./deploy.sh deploy             # 本地拉取 + 重启容器
#   ./deploy.sh release            # build + publish + deploy 一条龙
#   ./deploy.sh status             # 查看本地容器/镜像状态
#   ./deploy.sh rollback [tag]     # 回滚到指定 tag（默认回滚到上一个镜像）
#   ./deploy.sh login              # 引导登录 ACR
#
# 环境变量（可选，缺省走默认值）:
#   ACR_REGISTRY   阿里云 registry 地址，默认 registry.cn-hangzhou.aliyuncs.com
#   ACR_NAMESPACE  命名空间，默认 pengfit
#   ACR_IMAGE      镜像名，默认 dashboard
#   IMAGE_TAG      镜像 tag，默认 latest
# ----------------------------------------------------------------------------

set -euo pipefail

# ====================== 配置 ======================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"

ACR_REGISTRY="${ACR_REGISTRY:-registry.cn-hangzhou.aliyuncs.com}"
ACR_NAMESPACE="${ACR_NAMESPACE:-pengfit}"
ACR_IMAGE="${ACR_IMAGE:-dashboard}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

ACR_FULL_IMAGE="${ACR_REGISTRY}/${ACR_NAMESPACE}/${ACR_IMAGE}:${IMAGE_TAG}"
LOCAL_IMAGE="pengfit/${ACR_IMAGE}:${IMAGE_TAG}"

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
    command -v docker >/dev/null && docker compose version >/dev/null 2>&1 \
        || die "docker compose 不可用（需要 Docker 20.10+）"
}

# ====================== 子命令 ======================
cmd_build() {
    log "构建镜像: ${LOCAL_IMAGE}"
    cd "$WORKSPACE_ROOT"
    docker compose -f "$COMPOSE_FILE" build --no-cache
    ok "构建完成: ${LOCAL_IMAGE}"
}

cmd_publish() {
    cmd_build
    log "Tag → ${ACR_FULL_IMAGE}"
    docker tag "${LOCAL_IMAGE}" "${ACR_FULL_IMAGE}"
    
    # 检查 ACR 登录态
    if ! docker login --password-stdin -u "${ACR_USER:-}" "${ACR_REGISTRY}" </dev/null 2>/dev/null \
       && ! docker push "${ACR_FULL_IMAGE}" --dry-run 2>/dev/null; then
        warn "未登录 ${ACR_REGISTRY}（执行 ./deploy.sh login 引导登录，或手动: docker login ${ACR_REGISTRY}）"
        die "请先登录 ACR 再重试"
    fi
    
    log "推送镜像: ${ACR_FULL_IMAGE}"
    docker push "${ACR_FULL_IMAGE}"
    ok "推送完成: ${ACR_FULL_IMAGE}"
}

cmd_deploy() {
    log "重启本地容器（使用 ${LOCAL_IMAGE}）"
    cd "$WORKSPACE_ROOT"
    docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-deps dashboard
    
    # 健康检查
    log "等待健康检查..."
    local retries=30
    while (( retries-- > 0 )); do
        if curl -fsS http://localhost:5200/api/health >/dev/null 2>&1; then
            ok "服务在线: http://localhost:5200"
            return 0
        fi
        sleep 2
    done
    die "健康检查失败（30 次重试），请查看 docker logs gov-price-dashboard"
}

cmd_release() {
    cmd_publish
    cmd_deploy
}

cmd_status() {
    echo "=== 本地镜像 ==="
    docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}" \
        | grep -E "REPOSITORY|${ACR_IMAGE}" || true
    
    echo ""
    echo "=== 容器状态 ==="
    docker ps --filter "name=gov-price-dashboard" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
    
    echo ""
    echo "=== 健康检查 ==="
    if curl -fsS http://localhost:5200/api/health 2>/dev/null; then
        ok "API 在线"
    else
        warn "API 离线"
        return 1
    fi
}

cmd_login() {
    log "登录阿里云 ACR"
    echo "请输入阿里云账号（手机号/邮箱/子账号 RAM）和 ACR 控制台独立密码"
    echo "提示: ACR 密码 ≠ 阿里云账号密码，在 ACR 控制台 → 访问凭证 → 设置固定密码"
    echo ""
    docker login "${ACR_REGISTRY}"
}

cmd_rollback() {
    local target="${1:-}"
    if [[ -z "$target" ]]; then
        # 找上一个本地镜像 tag
        target=$(docker images --format "{{.Tag}}" "${LOCAL_IMAGE%:*}" \
                 | grep -v "^${IMAGE_TAG}$" | head -1)
        if [[ -z "$target" ]]; then
            die "没有可回滚的镜像"
        fi
        warn "未指定 tag，自动选: ${target}"
    fi
    
    log "回滚到 tag=${target}"
    cd "$WORKSPACE_ROOT"
    IMAGE_TAG="$target" docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-deps dashboard
    ok "回滚完成: tag=${target}"
}

cmd_help() {
    sed -n '2,15p' "$0" | sed 's/^# \?//'
}

# ====================== 主入口 ======================
preflight
case "${1:-help}" in
    build)    shift; cmd_build "$@" ;;
    publish)  shift; cmd_publish "$@" ;;
    deploy)   shift; cmd_deploy "$@" ;;
    release)  shift; cmd_release "$@" ;;
    status)   shift; cmd_status "$@" ;;
    rollback) shift; cmd_rollback "$@" ;;
    login)    shift; cmd_login "$@" ;;
    help|-h|--help) cmd_help ;;
    *) die "未知命令: $1（执行 $0 help 查看用法）" ;;
esac