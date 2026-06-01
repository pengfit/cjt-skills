#!/usr/bin/env python3
"""
Playwright 浏览器自动化：gov-price-dashboard 规格解析全流程

UI 限制：每次「抽」弹出抽样面板，确认录入规则后样本列表立即清空，
         无法批量处理，只能逐样本循环。

流程：
  1. 打开 dashboard → 数据入仓 tab
  2. 展开城市 → 点击 DWD 按钮 → 展开规格解析质量面板
  3. 按解析率最高优先遍历分类（< 100% 才处理）：
     a. 点击「抽」→ 弹出未解析样本
     b. 逐个处理：点击样本 → AI 分析 → 确认规则 → 关闭 fix
     c. 点击「洗」→ 等待清洗完成
     d. 循环：再次点击「抽」处理下一个样本（直到无未解析样本）
  4. 换下一个分类，直到所有分类 100%

用法：
  python3 playwright-auto-mine.py --city rizhao
  python3 playwright-auto-mine.py --city all
  python3 playwright-auto-mine.py --city rizhao --headless
"""

import argparse, time, sys

DASHBOARD_URL = "http://localhost:5300"
API_URL = "http://localhost:5200"
CITIES = ["xian", "sichuan", "chongqing", "jinan", "rizhao"]

CITY_LABELS = {
    "xian":      "西安",
    "sichuan":   "四川",
    "chongqing": "重庆",
    "jinan":     "济南",
    "rizhao":    "日照",
}

CITY_DWD_COUNTS = {
    "xian":      "68,304",
    "sichuan":   "92,921",
    "chongqing": "451",
    "jinan":     "7,744",
    "rizhao":    "2,102",
}

COVERAGE_DONE_THRESHOLD = 100


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── 页面操作工具 ─────────────────────────────────────────

def goto_provenance(page):
    tab = page.locator(".nav-tab").filter(has_text="数据入仓")
    tab.wait_for(state="visible", timeout=10000)
    if "active" not in (tab.get_attribute("class") or ""):
        tab.click()
    time.sleep(1)


def expand_city_card(page, city_label: str):
    for _ in range(3):
        ov = page.locator(".fix-overlay")
        if ov.is_visible():
            try:
                ov.locator(".fix-close").first.click()
                time.sleep(0.2)
            except Exception:
                ov.click(position={"x": 5, "y": 5})
                time.sleep(0.2)
        else:
            break
    cards = page.locator(".pipeline-card").all()
    for card in cards:
        city_el = card.locator(".pipeline-card-city")
        if city_el.is_visible() and city_label in city_el.inner_text():
            card.click()
            time.sleep(0.8)
            log(f"  展开城市：{city_label}")
            return True
    return False


def click_city_dwd_button(page, city_key: str):
    dwd_btns = page.locator(".pipe-stage-btn.stage-dwd").all()
    target_count = CITY_DWD_COUNTS.get(city_key, "")
    for btn in dwd_btns:
        txt = btn.inner_text()
        if target_count and target_count in txt:
            btn.click()
            time.sleep(1.5)
            log(f"  点击 DWD 按钮（{target_count}条）")
            return True
    idx = CITIES.index(city_key) if city_key in CITIES else 0
    dwd_btns[idx].click()
    time.sleep(1.5)
    log(f"  点击 DWD 按钮（fallback index={idx}）")
    return True


def ensure_sq_panel_visible(page):
    page.locator(".sq-panel").wait_for(state="visible", timeout=15000)
    time.sleep(0.3)


def get_sq_cards(page) -> list:
    return page.locator(".sq-card").all()


def get_card_info(page, card) -> dict:
    try:
        cat_el = card.locator(".card-cat")
        pct_el = card.locator(".card-pct")
        cat_el.wait_for(state="visible", timeout=3000)
        pct_el.wait_for(state="visible", timeout=3000)
        cat = cat_el.inner_text().strip()
        pct_str = pct_el.inner_text().strip().replace("%", "")
        try:
            pct = float(pct_str)
        except ValueError:
            pct = 0.0
        return {"cat": cat, "pct": pct}
    except Exception:
        return {"cat": "", "pct": 0.0}


def close_fix(page):
    """关闭 fix 弹窗（不关闭 modal）"""
    try:
        ov = page.locator(".fix-overlay")
        cl = page.locator(".fix-close")
        if ov.count() > 0 and ov.is_visible() and cl.count() > 0 and cl.is_visible():
            cl.first.click()
            ov.wait_for(state="hidden", timeout=5000)
    except Exception:
        pass


def _close_sample_modal(page):
    """关闭抽样面板"""
    try:
        page.locator(".sample-modal .btn-close").first.click()
        page.locator(".sample-modal").wait_for(state="hidden", timeout=5000)
    except Exception:
        pass


def _reopen_sample_panel(page, target_card):
    """重新点击「抽」打开抽样面板，返回是否成功"""
    try:
        sample_btn = target_card.locator(".btn-sample")
        sample_btn.wait_for(state="visible", timeout=5000)
        if sample_btn.is_disabled():
            return False
        sample_btn.click()
        page.locator(".sample-modal").wait_for(state="visible", timeout=15000)
        time.sleep(0.3)
        return True
    except Exception:
        return False


def wait_for_clean_done(page, timeout=120000):
    """等待清洗完成（loading spinner 消失）"""
    log(f"  等待清洗完成...")
    start = time.time()
    while time.time() - start < timeout:
        spinners = page.locator(".btn-clean .sp-xs")
        if spinners.count() == 0:
            elapsed = int(time.time() - start)
            log(f"  清洗完成（{elapsed}s）")
            time.sleep(3)
            return True
        time.sleep(3)
    log(f"  清洗超时")
    return False


def process_one_sample(page):
    """
    在已打开的抽样面板中处理一个未解析样本。
    返回 True=成功处理了样本，False=无可处理样本/出错
    """
    unparsed_list = page.locator(".ss-card.ss-empty").all()
    if not unparsed_list:
        return False

    unparsed = unparsed_list[0]
    try:
        spec_text = unparsed.locator(".ss-spec").inner_text().strip()[:40]
    except Exception:
        spec_text = "(未知)"
    log(f"\n  ── 样本：{spec_text}")

    try:
        unparsed.click()
    except Exception:
        return False

    # 等待 fix 弹窗
    try:
        page.locator(".fix-overlay").wait_for(state="visible", timeout=12000)
        time.sleep(0.3)
    except Exception:
        log(f"  fix-case 弹窗未出现，跳过")
        close_fix(page)
        return False

    # AI 分析
    ai_btn = page.locator(".btn-analyze")
    try:
        ai_btn.wait_for(state="visible", timeout=5000)
    except Exception:
        close_fix(page)
        return False
    if ai_btn.is_disabled():
        close_fix(page)
        return False

    ai_btn.click()
    log(f"  AI 分析中...")

    # 轮询等待规则建议（最多 45s，每 2s）
    start = time.time()
    sg_cards = []
    while time.time() - start < 45:
        sg_cards = page.locator(".fix-suggestion-card").all()
        if sg_cards:
            break
        time.sleep(2)

    if not sg_cards:
        log(f"  AI 生成规则超时")
        close_fix(page)
        return False

    sg_count = len(sg_cards)
    log(f"  AI 生成 {sg_count} 条规则")

    # 批量确认
    confirmed = 0
    for _ in range(sg_count + 3):
        sg_list = page.locator(".fix-suggestion-card").all()
        clicked = False
        for sg in sg_list:
            try:
                btn = sg.locator(".btn-confirm-fix")
                if not btn.is_visible() or btn.is_disabled():
                    continue
                txt = btn.inner_text().strip()
                if "已录入" in txt or "✓" in txt:
                    continue
                btn.click()
                confirmed += 1
                clicked = True
                time.sleep(0.3)
            except Exception:
                pass
        if not clicked:
            break

    log(f"  确认录入 {confirmed} 条规则")
    close_fix(page)
    time.sleep(0.3)
    return confirmed > 0


def process_category_one_pass(page, cat_name: str):
    """
    单次「抽」流程：打开抽样面板 → 处理所有未解析样本 → 清洗
    每次抽可以处理面板里的全部样本（前端在确认后列表清空，
    所以需要重新点击「抽」再处理下一批）
    返回 True=处理了至少1个样本
    """
    cards = page.locator(".sq-card").all()
    target_card = None
    for card in cards:
        try:
            if get_card_info(page, card)["cat"] == cat_name:
                target_card = card
                break
        except Exception:
            continue

    if not target_card:
        log(f"  未找到分类卡片：{cat_name}")
        return False

    rate = get_card_info(page, target_card)["pct"]
    if rate >= COVERAGE_DONE_THRESHOLD:
        log(f"  解析率 {rate}% ≥ {COVERAGE_DONE_THRESHOLD}%，跳过")
        return False

    log(f"\n  ▶ 处理分类「{cat_name}」（{rate}%）")

    # 点击「抽」
    sample_btn = target_card.locator(".btn-sample")
    sample_btn.wait_for(state="visible", timeout=5000)
    if sample_btn.is_disabled():
        log(f"  抽按钮禁用，跳过")
        return False

    sample_btn.click()
    time.sleep(0.3)

    try:
        page.locator(".sample-modal").wait_for(state="visible", timeout=15000)
    except Exception:
        log(f"  抽样面板未出现")
        return False

    log(f"  抽样面板已打开")

    # 循环处理面板内所有未解析样本
    samples_processed = 0
    while True:
        if process_one_sample(page):
            samples_processed += 1
        else:
            break

    log(f"  面板处理完成（{samples_processed} 个样本）")
    _close_sample_modal(page)
    time.sleep(0.3)

    if samples_processed == 0:
        return False

    # 重新定位卡片并点击「洗」
    cards2 = page.locator(".sq-card").all()
    target_card2 = None
    for card in cards2:
        try:
            if get_card_info(page, card)["cat"] == cat_name:
                target_card2 = card
                break
        except Exception:
            continue

    if not target_card2:
        log(f"  清洗时卡片消失，跳过")
        return samples_processed > 0

    clean_btn = target_card2.locator(".btn-clean")
    try:
        clean_btn.wait_for(state="visible", timeout=3000)
        if clean_btn.is_disabled():
            log(f"  洗按钮禁用，跳过")
        else:
            clean_btn.click()
            log(f"  清洗已触发（{samples_processed} 个样本）")
            wait_for_clean_done(page)
    except Exception:
        log(f"  洗按钮不可见，跳过")

    return True


def process_city(page, city_key: str):
    """处理整个城市"""
    city_label = CITY_LABELS.get(city_key, city_key)
    log(f"\n{'='*60}")
    log(f"▶ 开始处理城市：{city_label} ({city_key})")
    log(f"{'='*60}")

    goto_provenance(page)
    expand_city_card(page, city_label)
    click_city_dwd_button(page, city_key)
    ensure_sq_panel_visible(page)

    iteration = 0
    while iteration < 200:
        iteration += 1
        cards = get_sq_cards(page)

        # 选解析率最高且 < 100% 的分类
        best_card = None
        best_pct = 0.0
        for card in cards:
            try:
                info = get_card_info(page, card)
                pct = info["pct"]
                if pct < 100 and pct > best_pct:
                    best_pct = pct
                    best_card = card
            except Exception:
                continue

        if not best_card:
            log(f"  所有分类已达 100%")
            break

        cat_name = get_card_info(page, best_card)["cat"]
        log(f"\n  [{iteration}] 分类「{cat_name}」解析率 {best_pct}%")

        try:
            ok = process_category_one_pass(page, cat_name)
        except Exception as e:
            log(f"  出错: {e}")
            import traceback; traceback.print_exc()
            try:
                page.screenshot(path=f"/tmp/auto-mine-{city_key}-{cat_name[:8]}-err.png")
            except Exception:
                pass
            time.sleep(2)
            continue

        time.sleep(3)

        # 检查解析率
        cards_now = page.locator(".sq-card").all()
        final_pct = 0.0
        for c in cards_now:
            try:
                info = get_card_info(page, c)
                if info["cat"] == cat_name:
                    final_pct = info["pct"]
                    break
            except Exception:
                continue

        if final_pct >= 100:
            log(f"  ✅ 分类「{cat_name}」达 100%，换下一个")
        else:
            log(f"  分类「{cat_name}」{final_pct}%（< 100%），继续")

    log(f"\n  ✅ 城市 {city_label} 处理完成")


def run(cities, headless=False):
    cdp_url = "http://127.0.0.1:18800"
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(cdp_url)
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log(f"复用 OpenClaw 浏览器（CDP: {cdp_url}），当前 URL: {page.url}")
        for ov in page.locator(".fix-overlay, .sample-modal").all():
            if ov.is_visible():
                try:
                    ov.locator(".fix-close, .btn-close").first.click()
                except Exception:
                    ov.click(position={"x": 3, "y": 3})
                time.sleep(0.2)
        page.mouse.click(1, 1)
        if page.url and "localhost:5300" not in page.url:
            page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=30000)
            time.sleep(1.5)
    except Exception as e:
        log(f"CDP 连接失败（{e}），启动新浏览器")
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=30000)
        time.sleep(1.5)

    goto_provenance(page)

    for city_key in cities:
        for _ in range(3):
            ov = page.locator(".fix-overlay, .sample-modal")
            if not ov.is_visible():
                break
            try:
                ov.locator(".fix-close, .btn-close").first.click()
                time.sleep(0.2)
            except Exception:
                try: ov.click(position={"x": 3, "y": 3})
                except Exception: pass
        try:
            process_city(page, city_key)
        except Exception as e:
            log(f"处理城市 {city_key} 出错: {e}")
            import traceback; traceback.print_exc()
            try:
                page.screenshot(path=f"/tmp/auto-mine-{city_key}-fatal.png")
            except Exception:
                pass

    log("\n全部城市处理完成")
    pw.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="", help=f"城市（默认 rizhao），all=全部，可用: {', '.join(CITIES)}")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    if args.city == "all":
        target_cities = CITIES
    elif args.city:
        if args.city not in CITIES:
            print(f"未知城市: {args.city}，可用: {CITIES}")
            sys.exit(1)
        target_cities = [args.city]
    else:
        target_cities = ["rizhao"]

    log(f"目标城市：{target_cities}，headless={args.headless}")
    run(target_cities, headless=args.headless)