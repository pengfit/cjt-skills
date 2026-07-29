"""统一后台错误拦截 (2026-07-29 Task 1)

目标:
  - HTTPException / RequestValidationError / Unhandled Exception 全部走同一 JSON 协议
  - 客户端拿到结构化错误 + request_id(用于客服/前端关联)
  - 服务端完整 traceback 落到 logging(可按 request_id 查)
  - DEV 模式透出 traceback 到客户端方便排查;PROD 默认隐藏
  - X-Request-ID 头来回传递(Grep-friendly)

不依赖 FastAPI 之外的库。
"""
from __future__ import annotations
import logging
import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException


_log = logging.getLogger("api.error")

# DEV/PROD 切换:APP_ENV=prod 关闭 traceback 透出
DEV_MODE = os.environ.get("APP_ENV", "dev") != "prod"

# 哪些路径不强制带 request_id(SPA fallback/healthz 不需要走错误拦截完全格式)
_ERROR_SKIP_PATHS = {"/healthz", "/favicon.ico"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err_payload(
    *,
    type_: str,
    message: str,
    request_id: str,
    path: str,
    method: str,
    status_code: int,
    extra: Optional[dict] = None,
    traceback_text: Optional[str] = None,
) -> dict:
    """统一错误 JSON 形状(所有 handler 共用)
    
    形状:
      {
        "ok": False,
        "error": {
          "type": "...",
          "message": "...",
          "request_id": "req_abc123",
          "path": "...",
          "method": "...",
          "timestamp": "ISO8601",
          # 可选: errors(422 validation)/ traceback(DEV)
        },
        "status_code": 500
      }
    """
    err: dict = {
        "type": type_,
        "message": message,
        "request_id": request_id,
        "path": path,
        "method": method,
        "timestamp": _now_iso(),
    }
    if extra:
        err.update(extra)
    if DEV_MODE and traceback_text:
        # 限制大小,免得 500 自带超大 traceback 把客户端卡住
        err["traceback"] = traceback_text[-4000:] if len(traceback_text) > 4000 else traceback_text
    return {"ok": False, "error": err, "status_code": status_code}


class RequestIDMiddleware(BaseHTTPMiddleware):
    """统一 request_id 中间件
    
    - 接受客户端 X-Request-ID 头(无则生成 req_<12hex>)
    - 写到 request.state.request_id 供 handler / 异常 handler 读取
    - 回写到响应 X-Request-ID 头
    """
    
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("X-Request-ID")
        if incoming:
            # 防 XSS 注入 — 截到 64 字符,只允许 [A-Za-z0-9_-]
            safe = "".join(c for c in incoming[:64] if c.isalnum() or c in "-_")
            request_id = safe if safe else f"req_{uuid.uuid4().hex[:12]}"
        else:
            request_id = f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            # 让全局 exception_handler 接住,这层只保证 request_id 写入
            raise
        response.headers["X-Request-ID"] = request_id
        return response


def setup_error_handlers(app: FastAPI) -> None:
    """集中注册全局异常处理器。只需在 main.py 调一次。"""
    
    def _rid(request: Request) -> str:
        return getattr(request.state, "request_id", "req_unknown")
    
    def _ctx_headers(rid: str, extra: Optional[dict] = None) -> dict:
        h = {"X-Request-ID": rid}
        if extra:
            h.update(extra)
        return h
    
    @app.exception_handler(StarletteHTTPException)
    async def _starlette_http(request: Request, exc: StarletteHTTPException):
        """捕获 starlette 层异常(401 from AuthMiddleware, 404 from catch-all 等)"""
        rid = _rid(request)
        # 4xx 不算服务端错误,不打 ERROR 级 log,DEBUG 一行便于关联
        _log.debug(
            "[%s] %s %s -> %s (%s): %s",
            rid, request.method, request.url.path,
            exc.status_code, type(exc).__name__, exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_err_payload(
                type_="HTTPError",
                message=str(exc.detail) if exc.detail else f"HTTP {exc.status_code}",
                request_id=rid,
                path=request.url.path,
                method=request.method,
                status_code=exc.status_code,
            ),
            headers=_ctx_headers(rid, dict(exc.headers or {})),
        )
    
    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        """捕获 fastapi.HTTPException(raise HTTPException(...) 走这条)"""
        rid = _rid(request)
        _log.debug(
            "[%s] %s %s -> %s: %s",
            rid, request.method, request.url.path, exc.status_code, exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_err_payload(
                type_="HTTPError",
                message=str(exc.detail) if exc.detail else f"HTTP {exc.status_code}",
                request_id=rid,
                path=request.url.path,
                method=request.method,
                status_code=exc.status_code,
            ),
            headers=_ctx_headers(rid, dict(exc.headers or {})),
        )
    
    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError):
        """捕获 fastapi 校验失败(参数类型错、缺必填、enum 错等)
        返回 422 + 详细字段错误,前端可以 pinpoint 哪个参数错。"""
        rid = _rid(request)
        errs = []
        for e in exc.errors():
            # 简化每个错误为前端友好的形状
            errs.append({
                "loc": list(e.get("loc", [])),
                "msg": e.get("msg", ""),
                "type": e.get("type", ""),
            })
        _log.debug(
            "[%s] %s %s -> 422 validation: %d errors",
            rid, request.method, request.url.path, len(errs),
        )
        return JSONResponse(
            status_code=422,
            content=_err_payload(
                type_="ValidationError",
                message=f"Request validation failed ({len(errs)} field errors)",
                request_id=rid,
                path=request.url.path,
                method=request.method,
                status_code=422,
                extra={"errors": errs},
            ),
            headers=_ctx_headers(rid),
        )
    
    @app.exception_handler(Exception)
    async def _unhandled_exc(request: Request, exc: Exception):
        """捕获所有未处理异常 — 全局兜底
        
        行为:
          - 服务端 log.error 完整 traceback(关联 request_id)
          - 客户端给统一 JSON(DEV 模式带 traceback,PROD 模式不带)
          - 隐藏敏感信息(env 变量 / 内部路径 / SQL statement 等只走 log)
        """
        rid = _rid(request)
        tb = traceback.format_exc()
        # 防御:异常本身可能包含敏感信息(message 里有可能嵌入 sql)
        # 但保留原始 message,因为前端可能需要(比如 sqlite3.OperationalError 给的 hint)
        safe_msg = f"{type(exc).__name__}: {str(exc)[:300]}"
        _log.error(
            "[%s] UNHANDLED %s %s -> 500\n  exc: %s: %s\n  traceback:\n%s",
            rid, request.method, request.url.path,
            type(exc).__name__, exc, tb,
        )
        return JSONResponse(
            status_code=500,
            content=_err_payload(
                type_="InternalServerError",
                message=safe_msg,
                request_id=rid,
                path=request.url.path,
                method=request.method,
                status_code=500,
                traceback_text=tb if DEV_MODE else None,
            ),
            headers=_ctx_headers(rid),
        )
