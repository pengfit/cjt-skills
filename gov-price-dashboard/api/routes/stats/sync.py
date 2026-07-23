"""Phase 4 抽取: /api/stats/{city}-sync-progress + /api/stats/available-cities (原 main.py 内联实现)"""
from fastapi import APIRouter, HTTPException
from api.dependencies import es
from api.skill_registry import get as _registry_get, get_all as _registry_get_all

router = APIRouter()


@router.get("/api/stats/{city}-sync-progress")
def stats_sync_progress(city: str):
    """通用 sync-progress 端点（替代原 9 个手写端点）

    按 city key 从 skill registry 读 cfg，按 progress_mode 分发到：
      - period: heze/henan/qingdao/weihai
      - county: xian/chongqing
      - catalogue: sichuan/jinan/rizhao
    加新 skill：只需在 skill.yml 设 progress_mode + county_field/catalogue_field，
    无需改 dashboard 代码。
    """
    from api.routes.provenance import sync_progress as _prov_sync_progress
    cfg = _registry_get(city)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"未知 skill: {city}")
    try:
        return _prov_sync_progress(cfg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stats/available-cities")
def available_cities():
    """返回所有可查询的城市下拉选项（key + label）。

    CategoryTrendView 等用：只关心城市 key / label，不需要 progress / indices 等元数据。
    数据源与 /api/skill-registry 同源（扫盘 skill.yml）。
    """
    cities = [
        {"key": s["key"], "label": s.get("label", s["key"])}
        for s in _registry_get_all()
    ]
    return {"ok": True, "cities": cities}


    """记录用户提交的归一申请。
    落地路径：写入 workspace/scripts/norm_requests.log，便于离线批处理。
    重复提交去重（同品种 24h 内不重复记录）。
    """
    breed = (req.get("breed") or "").strip()
    if not breed:
        raise HTTPException(status_code=400, detail="breed 必填")

    log_path = Path.home() / ".openclaw" / "workspace" / "scripts" / "norm_requests.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # 24h 内去重
    now = datetime.now()
    if log_path.exists():
        with open(log_path) as f:
            for line in f.readlines()[-50:]:  # 只看最近 50 行
                parts = line.strip().split("\t")
                if len(parts) >= 2 and parts[1] == breed:
                    try:
                        last_ts = datetime.fromisoformat(parts[0])
                        if (now - last_ts).total_seconds() < 86400:
                            return {"ok": True, "duplicate": True, "breed": breed}
                    except Exception:
                        pass

    with open(log_path, "a") as f:
        f.write(f"{now.isoformat()}\t{breed}\tuser_requested\n")
    return {"ok": True, "breed": breed, "logged": str(log_path)}