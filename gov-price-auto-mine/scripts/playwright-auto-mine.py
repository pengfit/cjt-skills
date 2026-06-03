#!/usr/bin/env python3
"""
Playwright 浏览器自动化：gov-price-dashboard 规格解析全流程

UI 限制：每次「抽」弹出抽样面板，确认录入规则后样本列表立即清空，
         无法批量处理，只能逐样本循环。
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


def wait_visible(page, selector, timeout=15000, **kwargs):
    """等待元素可见，超时返回 False"""
    try:
        page.locator(selector).wait_for(state="visible", timeout=timeout, **kwargs)
        return True
    except Exception:
        return False


def wait_hidden(page, selector, timeout=15000, **kwargs):
    """等待元素隐藏，超时返回 False"""
    try:
        page.locator(selector).wait_for(state="hidden", timeout=timeout, **kwargs)
        return True
    except Exception:
        return False


def goto_provenance(page):
    tab = page.locator(".nav-tab").filter(has_text="数据清洗")
    tab.wait_for(state="visible", timeout=10000)
    if ("active" not in (tab.get_attribute("class") or "")):
        tab.click()
        time.sleep(2)  # 等待 tab 切换动画
        page.locator(".pipeline-card").first.wait_for(state="visible", timeout=10000)


def expand_city_card(page, city_label: str):
    # 清理可能遮盖的弹层
    for _ in range(3):
        ov = page.locator(".fix-overlay")
        if ov.is_visible():
            try:
                ov.locator(".fix-close").first.click()
                wait_hidden(page, ".fix-overlay", timeout=5000)
            except Exception:
                try: ov.click(position={"x": 5, "y": 5})
                except Exception: pass
        else:
            break

    cards = page.locator(".pipeline-card").all()
    for card in cards:
        city_el = card.locator(".pipeline-card-city")
        if city_el.is_visible() and city_label in city_el.inner_text():
            card.click()
            time.sleep(2)  # 等待城市卡片展开动画
            # 等待卡片展开动画完成（城市卡片切换时有过渡）
            page.locator(".stage-dwd .scrape-action-btn").first.wait_for(state="visible", timeout=8000)
            log(f"  展开城市：{city_label}")
            return True
    return False


def click_city_dwd_button(page, city_key: str):
    # 先找到城市卡片，再找该卡片的 DWD scrape-inner
    city_map = {"xian": "西安", "sichuan": "四川", "chongqing": "重庆", "jinan": "济南", "rizhao": "日照"}
    city_label = city_map.get(city_key, city_key)
    cards = page.locator(".pipeline-card").all()
    for card in cards:
        city_el = card.locator(".pipeline-card-city")
        if city_label in city_el.inner_text():
            # 找到该城市的 DWD scrape-inner
            dwd_stage = card.locator(".stage-dwd")
            dwd_stage.locator(".scrape-inner").first.click()
            time.sleep(2)
            page.locator(".dwd-drilldown-modal").wait_for(state="visible", timeout=10000)
            log(f"  点击 DWD（{city_label}）")
            return True
    return False


def ensure_sq_panel_visible(page):
    page.locator(".dwd-drilldown-modal").wait_for(state="visible", timeout=15000)


def get_sq_cards(page) -> list:
    return page.locator(".sq-card").all()


def get_card_info(page, card) -> dict:
    try:
        cat_el = card.locator(".card-cat")
        pct_el = card.locator(".card-pct")
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
    try:
        ov = page.locator(".fix-overlay")
        cl = page.locator(".fix-close")
        if ov.count() > 0 and ov.is_visible() and cl.count() > 0 and cl.is_visible():
            cl.first.click()
            wait_hidden(page, ".fix-overlay", timeout=5000)
    except Exception:
        pass


def _close_sample_modal(page):
    try:
        btn = page.locator(".sample-modal .btn-close")
        if btn.is_visible():
            btn.first.click()
            wait_hidden(page, ".sample-modal", timeout=5000)
    except Exception:
        # 弹窗可能已自行关闭
        pass


def wait_for_clean_done(page, timeout=120000):
    """等待清洗完成：检测 spinner 消失即为完成"""
    log(f"  等待清洗完成...")
    start = time.time()
    try:
        # 等待 .btn-clean 上的 spinner 消失（即 .sp-xs count == 0）
        page.locator(".btn-clean .sp-xs").wait_for(state="hidden", timeout=timeout)
        elapsed = int(time.time() - start)
        log(f"  清洗完成（{elapsed}s）")
        return True
    except Exception:
        log(f"  清洗超时")
        return False


def process_one_sample(page):
    # ⚠️ 每次重新查询 DOM，不缓存 locators
    unparsed_list = page.locator(".ss-card.ss-empty").all()
    if not unparsed_list:
        return None  # 没有更多未解析样本了（面板可能还在，等下一轮）

    unparsed = unparsed_list[0]
    try:
        spec_text = unparsed.locator(".ss-spec").inner_text().strip()[:40]
    except Exception:
        spec_text = "(未知)"
    log(f"\n  ── 样本：{spec_text}")

    try:
        unparsed.click()
    except Exception:
        log(f"  样本点击失败，跳过")
        return False

    try:
        page.locator(".fix-overlay").wait_for(state="visible", timeout=12000)
    except Exception:
        log(f"  fix-case 弹窗未出现，跳过")
        close_fix(page)
        return False

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
    time.sleep(2)  # 等待 AI 开始处理

    # 等待 AI 生成的规则卡片出现（事件驱动，不再轮询）
    try:
        page.locator(".fix-suggestion-card").first.wait_for(state="visible", timeout=45000)
    except Exception:
        log(f"  AI 生成规则超时")
        close_fix(page)
        return False

    # 等待规则卡片全部渲染完成
    page.wait_for_timeout(300)

    sg_count = page.locator(".fix-suggestion-card").count()
    log(f"  AI 生成 {sg_count} 条规则")
    time.sleep(2) 
    # 逐个确认规则，直到没有可点的按钮为止
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
                time.sleep(2) 
                confirmed += 1
                clicked = True
                # 等待按钮状态更新
                page.locator(".fix-suggestion-card .btn-confirm-fix").wait_for(state="visible", timeout=3000)
            except Exception:
                pass
        if not clicked:
            break

    log(f"  确认录入 {confirmed} 条规则")
    time.sleep(3)  # 等待规则确认落库
    close_fix(page)
    time.sleep(2)  # 等待弹窗关闭动画
    return True if confirmed > 0 else False


def process_category_one_pass(page, cat_name: str):
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

    sample_btn = target_card.locator(".btn-sample")
    sample_btn.wait_for(state="visible", timeout=5000)
    if sample_btn.is_disabled():
        log(f"  抽按钮禁用，跳过")
        return False

    sample_btn.click()
    page.locator(".sample-modal").wait_for(state="visible", timeout=15000)
    time.sleep(2)  # 等待抽样面板动画完成

    log(f"  抽样面板已打开")

    samples_processed = 0
    ai_timeout_count = 0
    max_ai_timeout = 2  # 连续 2 次 AI 超时则放弃本轮

    while True:
        # 面板消失则退出
        if page.locator(".sample-modal").count() == 0:
            log(f"  抽样面板已消失，停止处理")
            break
        if not page.locator(".sample-modal").is_visible():
            log(f"  抽样面板不可见，停止处理")
            break

        ok = process_one_sample(page)
        if ok is None:
            # 没有更多未解析样本，但面板还在，等一会儿看是否有刷新
            time.sleep(2)
            unparsed_now = page.locator(".ss-card.ss-empty").count()
            if unparsed_now > 0:
                # 有新样本了，继续下一轮
                continue
            try:
                page.locator(".ss-card.ss-empty").wait_for(state="attached", timeout=3000)
            except Exception:
                # 3s 内没有新样本，视为耗尽
                log(f"  样本耗尽，停止处理")
                break
        elif ok is True:
            samples_processed += 1
            ai_timeout_count = 0  # 重置超时计数
        else:
            # AI 超时（返回 False）
            ai_timeout_count += 1
            log(f"  AI 超时（连续 {ai_timeout_count}/{max_ai_timeout}）")
            # 检查面板是否消失，如果是则退出，不消失则重试
            if page.locator(".sample-modal").count() == 0 or not page.locator(".sample-modal").is_visible():
                log(f"  面板已关闭，中断本分类")
                break
            if ai_timeout_count >= max_ai_timeout:
                log(f"  连续超时次数过多，停止处理")
                break

    log(f"  面板处理完成（{samples_processed} 个样本）")
    _close_sample_modal(page)
    time.sleep(2)  # 等待面板关闭动画

    # 有规则确认 或 样本耗尽，都应该触发洗
    if samples_processed == 0 and ai_timeout_count == 0:
        # 样本耗尽但无规则确认（已有规则全部确认过），不需要洗
        log(f"  无新规则确认，跳过清洗")
        return False

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
            time.sleep(2)  # 等待清洗启动
            wait_for_clean_done(page)
            time.sleep(20)  # 清洗完成后让界面稳定
    except Exception:
        log(f"  洗按钮不可见，跳过")

    return True


def process_city(page, city_key: str):
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

        best_card = None
        best_info = None
        for card in cards:
            try:
                info = get_card_info(page, card)
                if info["pct"] < 100 and (best_info is None or info["pct"] > best_info["pct"]):
                    best_info = info
                    best_card = card
            except Exception:
                continue

        if not best_card:
            log(f"  所有分类已达 100%")
            break

        cat_name = best_info["cat"]
        cat_pct_before = best_info["pct"]
        log(f"\n  [{iteration}] 分类「{cat_name}」解析率 {cat_pct_before}%")

        try:
            ok = process_category_one_pass(page, cat_name)
            # 验证进度是否真正提升（防止卡在同一个样本上）
            time.sleep(1)  # 等界面刷新
            cards_after = get_sq_cards(page)
            new_pct = None
            for card in cards_after:
                try:
                    info = get_card_info(page, card)
                    if info["cat"] == cat_name:
                        new_pct = info["pct"]
                        break
                except Exception:
                    continue
            if new_pct is not None and new_pct <= cat_pct_before:
                log(f"  ⚠ 解析率未提升（{cat_pct_before}% → {new_pct}%），重试该分类")
            elif new_pct is not None:
                log(f"  解析率提升：{cat_pct_before}% → {new_pct}%")
        except Exception as e:
            log(f"  出错: {e}")
            import traceback; traceback.print_exc()
            try:
                page.screenshot(path=f"/tmp/auto-mine-{city_key}-{cat_name[:8]}-err.png")
            except Exception:
                pass
            page.locator(".fix-overlay, .sample-modal").filter(visible=True).first.click(position={"x": 3, "y": 3})
            page.wait_for_timeout(500)
            continue

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
                wait_hidden(page, ".fix-overlay, .sample-modal", timeout=5000)
        page.mouse.click(1, 1)
        if page.url and "localhost:5300" not in page.url:
            page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=30000)
            page.locator(".pipeline-card").first.wait_for(state="visible", timeout=15000)
    except Exception as e:
        log(f"CDP 连接失败（{e}），启动新浏览器")
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=30000)
        page.locator(".pipeline-card").first.wait_for(state="visible", timeout=15000)

    goto_provenance(page)

    for city_key in cities:
        for _ in range(3):
            ov = page.locator(".fix-overlay, .sample-modal")
            if not ov.is_visible():
                break
            try:
                ov.locator(".fix-close, .btn-close").first.click()
                wait_hidden(page, ".fix-overlay, .sample-modal", timeout=3000)
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