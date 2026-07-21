#!/usr/bin/env python3
"""
snapshot_showcase.py — 用 Playwright + 自签 JWT 跑 /trend 截图
为 /home 的案例轮播图供图。

输出：frontend/public/showcase/snapshots/{NN}-{slug}.png

用法：
  cd skills/gov-price-dashboard
  export JWT_SECRET="$(grep ^JWT_SECRET api/.env.auth | cut -d= -f2)"
  python3 scripts/snapshot_showcase.py            # 全量: 全国 + 19 城
  python3 scripts/snapshot_showcase.py --only xian  # 仅某城 + 全国
  BREED="热轧带肋钢筋" python3 scripts/snapshot_showcase.py
"""

import os
import sys
import time
import argparse
import yaml
from pathlib import Path
from playwright.sync_api import sync_playwright
from jose import jwt

# ── 路径与配置 ────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT.parent          # cjt/skills
SNAPSHOTS = ROOT / "frontend/public/showcase/snapshots"
ENV_FILE = ROOT / "api/.env.auth"

DASHBOARD = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:5300")
DEFAULT_BREED = "商品混凝土"
DEFAULT_VP = {"width": 1440, "height": 900}


def load_jwt_secret() -> str:
    """优先取环境变量，其次从 api/.env.auth 读"""
    secret = os.environ.get("JWT_SECRET", "").strip()
    if secret:
        return secret
    if not ENV_FILE.exists():
        sys.exit(f"Error: JWT_SECRET 未设, 且 {ENV_FILE} 不存在")
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("JWT_SECRET="):
            return line.split("=", 1)[1].strip()
    sys.exit("Error: 未在 api/.env.auth 找到 JWT_SECRET")


def list_cities() -> list:
    """扫 skills/*/skill.yml, 取 (key, label, province)"""
    cities = []
    for yml in sorted(SKILLS_DIR.glob("*/skill.yml")):
        cfg = yaml.safe_load(yml.read_text()) or {}
        if cfg.get("dws_index") and cfg.get("key") and cfg.get("label"):
            cities.append({
                "key": cfg["key"],
                "label": cfg["label"],
                "province": cfg.get("province", ""),
            })
    return cities


def gen_token(secret: str, ttl: int = 3600) -> str:
    """自签 admin JWT (绕登录 UI,直接 localStorage 注入)"""
    now = int(time.time())
    return jwt.encode(
        {"sub": "admin", "role": "admin", "iat": now, "exp": now + ttl},
        secret,
        algorithm="HS256",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="只截某个 key (如 xian), 同时保留全国基线")
    parser.add_argument("--breed", default=os.environ.get("BREED", DEFAULT_BREED),
                        help=f"跨城归一品类 (默认: {DEFAULT_BREED})")
    parser.add_argument("--wait", type=int, default=2200,
                        help="echarts 渲染稳态等待 ms (默认 2200)")
    args = parser.parse_args()

    secret = load_jwt_secret()
    cities = list_cities()
    sequence = [{"key": "__nation__", "label": "全国跨城", "province": ""}] + cities
    if args.only:
        sequence = [c for c in sequence if c["key"] in ("__nation__", args.only)]

    print(f"[snapshot] JWT_SECRET 长度={len(secret)}, {len(sequence)} 张待截, breed={args.breed!r}")
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)

    token = gen_token(secret)
    user_blob = '{"username":"admin","role":"admin"}'

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(viewport=DEFAULT_VP)
        page = ctx.new_page()

        # 先去 /login 注入 token + user, 之后所有请求都带 JWT
        page.goto(f"{DASHBOARD}/login", wait_until="domcontentloaded")
        page.evaluate(
            "(t) => localStorage.setItem('cjt_jwt', t)", token)
        page.evaluate(
            "(u) => localStorage.setItem('cjt_user', u)", user_blob)

        ok, fail = 0, 0
        for idx, c in enumerate(sequence, start=1):
            qs = f"breed={args.breed}"
            if c["key"] != "__nation__":
                qs += f"&city={c['key']}"
            url = f"{DASHBOARD}/trend?{qs}"
            slug = "nation" if c["key"] == "__nation__" else c["key"]
            out = SNAPSHOTS / f"{idx:02d}-{slug}.png"

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_selector("canvas", state="attached", timeout=15000)
                page.wait_for_timeout(args.wait)
                page.screenshot(path=str(out), full_page=False)
                print(f"  ✓ {out.name:<25} {c['label']}({c['province']})")
                ok += 1
            except Exception as e:
                print(f"  ✗ {c['label']:<10} {e}")
                fail += 1

        browser.close()

    print(f"\n[done] {ok} ok / {fail} fail -> {SNAPSHOTS}")


if __name__ == "__main__":
    main()
