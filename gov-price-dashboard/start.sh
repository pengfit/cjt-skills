#!/bin/bash
# gov-price-dashboard 启动脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 加载 .env.auth (JWT_SECRET 等) — 不加载会拒绝启动
# 注：不能用 `set -a; . file` 直接 source,ADMIN_HASH 里的 $2b$... 会被 bash 当变量展开损坏
# 这里逐行读并 export 字面值
if [ -f "$SCRIPT_DIR/.env.auth" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # 跳注释 / 空行
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        key="${line%%=*}"
        val="${line#*=}"
        # 只接受合法的环境变量名
        [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && export "$key=$val"
    done < "$SCRIPT_DIR/.env.auth"
fi

start_api() {
    echo "启动 API 服务 (http://localhost:5200)..."
    cd "$SCRIPT_DIR/api"
    nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 5200 > /tmp/gov-price-api.log 2>&1 &
    echo "API PID: $!"
}

start_frontend() {
    echo "启动前端服务 (http://localhost:5300)..."
    cd "$SCRIPT_DIR/frontend"
    nohup npm run dev -- --port 5300 --host 0.0.0.0 > /tmp/gov-price-frontend.log 2>&1 &
    echo "Frontend PID: $!"
}

status() {
    echo "=== API ===" && curl -s http://localhost:5200/health 2>/dev/null || echo "API 未运行"
    echo "=== Frontend ===" && curl -s http://localhost:5300 2>/dev/null | head -1 || echo "Frontend 未运行"
}

stop() {
    kill $(lsof -t -i:5200) 2>/dev/null && echo "API 已停止" || echo "API 未运行"
    kill $(lsof -t -i:5300) 2>/dev/null && echo "Frontend 已停止" || echo "Frontend 未运行"
}

case "${1:-start}" in
    start) start_api; sleep 2; start_frontend; echo "全部启动完成" ;;
    status) status ;;
    stop) stop ;;
    restart) stop; sleep 1; start_api; sleep 2; start_frontend; echo "全部重启完成" ;;
    *) echo "用法: $0 {start|stop|restart|status}" ;;
esac
