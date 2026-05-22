#!/bin/bash
# gov-price-dashboard 启动脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
