from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import os, sys, sqlite3
import yaml
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 分类库路径（2026-07-09 起统一到 breed_canonical.db）
# 原 category_v3_rules.db 仍由 gov-price-etl 写入，但 dashboard 层改读 breed_canonical.db
# 路径统一从 api.paths 推导（单一来源，只读 SKILLS_ROOT 环境变量）
from api.paths import CATEGORY_DB  # noqa: E402

# 共享依赖（ES client + 索引集 ALL/LIST/DWD/ODS/NORM + ES_HOST/ES_INDEX）
from api.dependencies import (  # noqa: E402
    es,
    ES_HOST,
    ES_INDEX,
    ALL_INDICES,
    LIST_INDICES,
    ALL_DWD_INDICES,
    ALL_ODS_INDICES,
    NORM_INDICES,
)

# 共享 helper（ES bool 查询 + 安全调用 + 索引过滤）
from api.helpers import (  # noqa: E402
    _build_bool_query,
    safe_search,
    safe_count,
    safe_total_count,
    EMPTY_SEARCH,
)

# 集中引用 skill registry（仅 get/get_all 供路由查 skill 信息）
from api.skill_registry import (
    get_all as _registry_get_all,
    get as _registry_get,
)
# 索引集的初始化已迁移到 api/dependencies（ALL_INDICES/LIST_INDICES/ALL_DWD/ALL_ODS/NORM_INDICES）

app = FastAPI(title="材价通 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2026-07-19 全局鉴权 middleware(刀切)
# 规则:/api/* 全部要求 admin JWT,仅 /api/auth/login 公开
# (因为 /api/auth/me 与 /api/auth/logout 仍需 token,不算严格公众)
# /api/health 改迁 /healthz(docker healthcheck 用),跳出 /api/
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from api.auth import JWT_SECRET, JWT_ALG, decode_token
from jose import JWTError
_PUBLIC_PATHS = {
    "/api/auth/login",
    "/api/",
    "/api",
    "/api/showcase/stats",
    "/api/showcase/insight",
    # 2026-07-21: /market 公开页(涨跌幅/热门品类/热力图),不需 JWT
    "/api/market/overview",
    "/api/market/movers",
    "/api/market/hot-categories",
    "/api/market/change-heatmap",
    "/api/market/spec-fingerprints",
    "/api/market/attr-keys",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """对所有 /api/* 路径强制 JWT 鉴权(/api/auth/login 除外)"""

    async def dispatch(self, request, call_next):
        path = request.url.path
        # 非 /api/ 路径(SPA、static、/healthz 等)直接放过
        if not path.startswith("/api/") and path != "/api":
            return await call_next(request)
        # 白名单
        if path in _PUBLIC_PATHS:
            return await call_next(request)
        # 取 Bearer token
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"detail": "missing Authorization header"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = auth[7:].strip()
        try:
            # 直接复用 decode_token 的逻辑,但走原始 jwt.decode 不要抛 HTTPException
            from jose import jwt as _jwt
            payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        except JWTError as e:
            return JSONResponse(
                {"detail": f"invalid token: {e}"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        # 把 user 信息挂到 request.state,后续路由可以直接读
        request.state.user = payload
        return await call_next(request)


app.add_middleware(AuthMiddleware)

from api.routes.auth import router as auth_router
app.include_router(auth_router)  # 公开（登录/验证 token）
from api.auth import get_current_user
from fastapi import Depends
# 2026-07-19：所有业务路由都要求 admin JWT（/api/auth/* 与 /api/health 仍公开）
_PROTECTED = {"dependencies": [Depends(get_current_user)]}
from api.routes.provenance import router as provenance_router
app.include_router(provenance_router, **_PROTECTED)
from api.routes.trend import router as trend_router
app.include_router(trend_router, **_PROTECTED)
from api.routes.breed_recommend import router as breed_recommend_router
app.include_router(breed_recommend_router, **_PROTECTED)
from api.routes.norm_search import router as norm_search_router
app.include_router(norm_search_router, **_PROTECTED)
from api.routes.category_trend import router as category_trend_router
app.include_router(category_trend_router, **_PROTECTED)

# 2026-07-19：对外展示页聚合数据（公开，不需要 JWT）
# 只读 ES 聚合 + skill registry,无原始数据泄露
from api.routes.showcase import router as showcase_router
# v0.18+ v2 (2026-07-23): 复原 showcase 为公开 — /home 落地页访客直访,
# showcase 数据是聚合统计(无原始价格/spec/attr 泄露),保持公开合理
app.include_router(showcase_router)

# 2026-07-21：/market 市场行情公开 API（涨跌幅/热门品类/热力图）
# 同样只读 ES 聚合,返回的字段已脱敏(无原始 spec/attr,只有均价)
from api.routes.market import router as market_router
app.include_router(market_router)

# 2026-07-23: 搜索 / 分类树 / 筛选选项 路由抽取
from api.routes.search import router as search_router
app.include_router(search_router, **_PROTECTED)
# 2026-07-23: /list 页专用路由组 (DWS via LIST_INDICES)
from api.routes.list import router as list_router
app.include_router(list_router, **_PROTECTED)
# 2026-07-23: /distribution 页专用路由组 (NORM via NORM_INDICES)
from api.routes.norm_distribution import router as norm_distribution_router
app.include_router(norm_distribution_router, **_PROTECTED)
# 2026-07-23: /trend 页专用路由组 (NORM via norm_{city}_price,无 DWS fallback)
from api.routes.norm_trend import router as norm_trend_router
app.include_router(norm_trend_router, **_PROTECTED)

# 2026-07-23: stats/ 12 个端点路由抽取（distribution/category/breed/health/sync/geo）;overview 接口已删
from api.routes.stats.distribution import router as stats_distribution_router
app.include_router(stats_distribution_router, **_PROTECTED)
from api.routes.stats.category import router as stats_category_router
app.include_router(stats_category_router, **_PROTECTED)
from api.routes.stats.breed import router as stats_breed_router
app.include_router(stats_breed_router, **_PROTECTED)
from api.routes.stats.health import router as stats_health_router
app.include_router(stats_health_router, **_PROTECTED)
from api.routes.stats.sync import router as stats_sync_router
app.include_router(stats_sync_router, **_PROTECTED)
from api.routes.stats.geo import router as stats_geo_router
app.include_router(stats_geo_router, **_PROTECTED)
from api.routes.stats.norm import router as stats_norm_router
app.include_router(stats_norm_router, **_PROTECTED)

# 2026-07-23: skill 路由抽取（3 个端点：updates / registry / registry-reload）
from api.routes.skill import router as skill_router
app.include_router(skill_router, **_PROTECTED)

@app.get("/api/", include_in_schema=False)
def api_info():
    return {"message": "材价通 API", "version": "1.0.0", "docs": "/healthz"}


