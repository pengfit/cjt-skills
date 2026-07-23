"""Phase 6 抽取: /api/stats/norm-request (原 stats/sync.py,现独立 norm.py)"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Body

router = APIRouter()


@router.post("/api/stats/norm-request")
def norm_request(req: dict = Body(...)):
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