from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
import os, sys, sqlite3
import yaml
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 分类库路径（2026-07-09 起统一到 breed_canonical.db）
# 原 category_v3_rules.db 仍由 gov-price-etl 写入，但 dashboard 层改读 breed_canonical.db
# 路径统一从 api.paths 推导（单一来源，只读 SKILLS_ROOT 环境变量）
from api.paths import CATEGORY_DB  # noqa: E402
# 2026-07-29 Task 1:统一后台错误拦截 (request_id 注入 + 4 层 exception_handler)
from api.error_handler import setup_error_handlers, RequestIDMiddleware, _err_payload  # noqa: E402

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

app = FastAPI(title="ChinaJT API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 2026-07-29 Task 1:全局异常处理函数 setup 在此处(装上 @app.exception_handler)。
# 中间件的 add 顺序: Starlette 末位 add = 最外层 = 最先跑。
# RequestIDMiddleware 必须加在 AuthMiddleware 之后,让 request_id 在鉴权检查之前
# 就写入 request.state + response.headers["X-Request-ID"]。
setup_error_handlers(app)

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
    # 2026-07-23 v0.23: /market 搜索端点(返回品种+规格信息供用户选)
    "/api/market/breed-search",
    # 2026-07-23 v0.25: /market 默认随机展示(12 个产品)
    "/api/market/random-breeds",
    # 2026-07-23 v0.33: 相邻品种推荐(按 l1/l2/l3 + spec_attrs 排序,用于搜索时更新推荐区)
    "/api/market/related-breeds",
    # 2026-07-25: /market 「数据来源」模块 — 全量源站清单(按省分组)
    "/api/market/sources",
    # 2026-07-25: /market 「数据治理透明卡」 — 每城新鲜度/attr_norm 覆盖
    "/api/market/data-quality",
    # 2026-07-25: /market (A.2) 热力图行标签下的 sparkline 历史折线
    "/api/market/sparkline",
    # 2026-07-27:趋势卡专用,单品种按城绝对价,公开(/market 页用)
    "/api/market/breed-trend",
    # 2026-07-28 v3:/market 双卡片公开端点(价格走势 + 时序数据表)
    #   与 /api/norm/price-trend 同源 NORM 数据, 但 /market/ 前缀 + 收紧参数
    "/api/market/price-trend",
    "/api/market/trend-table",
    # 2026-07-28 v3.1:/market 双卡片 toolbar 下拉用 — 列出 NORM 已 ETL 城市
    "/api/market/cities",
    # 2026-07-28:浏览器 GPS 反查中国省份名(Nominatim 代理),公开(/market 首屏定位用)
    "/api/market/geo-locate",
    # 2026-07-28:GPS 定位后展示用 — 单省份多品种 × 月度均价趋势(单 query 拿 10 品种 × 6 月),公开
    "/api/market/province-trend",
    # 2026-07-27:品种归一后台(只读 breed_canonical.db,只返脱敏字段,公开)
    "/api/canon/breeds/stats",
    # 2026-07-29:/market 页面 PV 计数器(POST 自增 + GET 只读,公开)
    "/api/market/visit",
    "/api/market/stats",
    "/api/canon/breeds",
    # 2026-07-27:分类映射后台(只读 breed_l3_map_v3,只返 breed_clean/l3/source/confidence,公开)
    "/api/stats/breed-l3-map/stats",
    "/api/stats/breed-l3-map",
    # 2026-07-27:/taxonomy 公共页调(只返分类骨架统计,无敏感数据)
    "/api/stats/category-v2-stats",
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
            return _unauth_response(request, "missing Authorization header")
        token = auth[7:].strip()
        try:
            # 直接复用 decode_token 的逻辑,但走原始 jwt.decode 不要抛 HTTPException
            from jose import jwt as _jwt
            payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        except JWTError as e:
            return _unauth_response(request, f"invalid token: {e}")
        # 把 user 信息挂到 request.state,后续路由可以直接读
        request.state.user = payload
        return await call_next(request)


def _unauth_response(request, detail: str) -> JSONResponse:
    """401 鉴权失败 → 走与全局 exception_handler 一致的统一 JSON 形状
    (绕过 Starlette 对 BaseHTTPMiddleware 中 raise HTTPException 的包住默认处理,
     直接复用 _err_payload 构造,避免双套处理逻辑漂移)"""
    rid = getattr(request.state, "request_id", None) or "req_unknown"
    body = _err_payload(
        type_="HTTPError",
        message=detail,
        request_id=rid,
        path=request.url.path,
        method=request.method,
        status_code=401,
    )
    return JSONResponse(
        body,
        status_code=401,
        headers={"WWW-Authenticate": "Bearer", "X-Request-ID": rid},
    )


# 2026-07-29 Task 1:Auth 加在前面(内层),RequestID 加在最后(最外层)
# → 执行顺序:RequestID → CORSMiddleware → Auth → handler。
# Auth 报 401 时,Response 流回栈,RequestID 的"after call_next"代码自动追加 X-Request-ID。
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestIDMiddleware)

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
from api.routes.canon import router as canon_router
from api.routes.breed_l3_map import router as breed_l3_map_router
app.include_router(market_router)
app.include_router(canon_router)  # 2026-07-27:治理页读操作先 public(/market 也公开同源数据,没风险)
app.include_router(breed_l3_map_router)  # 2026-07-27:数据治理读操作 public(同类 canon, /market 也公开同源数据)

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
# 2026-07-28 v3: 恢复 _PROTECTED — /market 双卡片改走新建的 /api/market/{price-trend,trend-table}
#   /api/norm/price-trend 仍归 /trend 页专用,鉴权后访问
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
    return {"message": "ChinaJT API", "version": "1.0.0", "docs": "/healthz"}


# 2026-07-23: 补回 /healthz 公开探针。Phase 7 把 main.py 收到 171 行时把
# 原 /api/health 改迁到 /healthz 的迁移丢了,deploy.sh wait_for_health 的兜底
# 探测一直 404。AuthMiddleware 在 line ~80 已自动放过非 /api/ 路径,
# 此处不需要 Depends(get_current_user)。
# 用途: deploy.sh health 探测 + 外部 LB 健康检查。
@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


# 2026-07-23: SPA fallback 回归修复。Phase 4 把 main.py 砍到 171 行时把
# StaticFiles 挂载 + catch-all 一起带走了,导致 /home /cockpit /dist 等 SPA 路由
# 与 /assets/*.js 等静态资源全部 404。AuthMiddleware line ~80 已自动放过
# 非 /api/ 路径,这里不需要 Depends。
#
# vite.config.js 无 base 字段 → 默认 /,所以 dist/index.html 引用:
#   /assets/index-XXX.js  (打包后的 JS/CSS)
#   /avatar-*.png /favicon.svg  (散落的静态资源)
#   /geo/ /img/ /screenshots/ /showcase/  (子目录)
#
# 模式:
#   - /assets 走 StaticFiles 直送(高效,大文件走 sendfile)
#   - catch-all: 文件存在直送(avatar/favicon/geo/img 等),否则返回 index.html
#     让 vue-router 接管 — 这是 Vue SPA 的标准做法
# 2026-07-23: 路径双模式兼容
# - docker 模式: WORKDIR=/app + Dockerfile 把 frontend/dist 拷为 ./static,走 _DOCKER_STATIC
# - dev 模式: 项目根有 frontend/dist/ 但没有 static/,走 _DEV_STATIC
# 运行时二选一,两条路径都能找到 dist/
_HERE = os.path.dirname(os.path.abspath(__file__))
_DASHBOARD_ROOT = os.path.dirname(_HERE)
_DOCKER_STATIC = os.path.join(_DASHBOARD_ROOT, "static")
_DEV_STATIC = os.path.join(_DASHBOARD_ROOT, "frontend", "dist")
STATIC_DIR = _DOCKER_STATIC if os.path.isdir(_DOCKER_STATIC) else _DEV_STATIC
app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

@app.get("/{full_path:path}", include_in_schema=False)
async def spa_catch_all(full_path: str):
    # 安全兜底:不要拦 /api/* 路径(虽然 AuthMiddleware 不挡 /api/,但 include_router
    # 已在 catch-all 之前注册,/api/* 会先匹配到 router 不会到这里)
    if full_path.startswith("api/") or full_path.startswith("assets/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    # 真实存在的静态文件 → 直送(avatar / favicon / 子目录等)
    potential = os.path.join(STATIC_DIR, full_path)
    if os.path.isfile(potential):
        return FileResponse(potential)
    # 2026-07-26 #SEO: 目录形式 prerender(/home/index.html /market/index.html)
    #   vite seoBuildPlugin 为公开路由生成 dist/{path}/index.html,
    #   /home → static/home 是目录(上面 isfile False),改成也查 {path}/index.html
    dir_index = os.path.join(potential, "index.html")
    if os.path.isfile(dir_index):
        return FileResponse(dir_index)
    # SPA 路由(/home /cockpit /dist ... 等) → 返回 index.html
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


