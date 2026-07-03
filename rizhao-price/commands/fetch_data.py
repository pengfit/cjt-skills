"""fetch_data.py - 日照源站抓取（v1.1 Playwright 内部 fetch, 2026-07-03）

v1.1 重大发现（2026-07-03 反编译 SPA axios 调用）：
  源站 SPA 内部走 axios POST 调 REST endpoint：
    POST http://58.59.43.227:81/EpointSDRZ/rest/zjzmaterialpriceserver/getreleaseprice
    Content-Type: application/x-www-form-urlencoded
    Body: 裸 JSON 字符串（不是 form-encoded 的 params=...）
          {"params":"{...escaped inner json...}"}
  
  关键差异（v1.1）：
    1. periods 字段接受历史期（'2026-1' ~ '2026-5'）→ 支持回溯 1-5 月
    2. pageIndex 起始是 0（不是 1）→ pageIndex=0 是首页
    3. pageSize 上限 2000（实测 2000 能一次性拿 1084 条 tab1）
    4. Body 必须是裸 JSON 字符串（axios 默认行为）→ 纯 Python requests 不行
       必须在 Playwright page.evaluate 里发 fetch 才能用浏览器 session
    5. 5 个月 × 3 tab = 15 个 unit，1 次浏览器启动约 30 秒

公开 API：
    from fetch_data import fetch_one, get_current_period, TAB_NAMES
    rows = fetch_one(period='2026-05', tab_type='1')
    # → [{'clmc': '普线', 'ggxh': 'Φ6.5 Q235', ...}, ...]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import List, Dict, Optional, Tuple

# 源站 endpoint（v1.1 反编译自 SPA axios 调用）
ENDPOINT = 'http://58.59.43.227:81/EpointSDRZ/rest/zjzmaterialpriceserver/getreleaseprice'

# tabType → 名称（与 v0 utils.TAB_TYPES 一致）
TAB_NAMES = {
    '1': '建设工程材料',
    '2': '园林绿化苗木',
    '3': '区县建设工程材料',
}

# 浏览器路径（沿用 v0）
CHROME_PATH = '/Users/pengfit/Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'

# 内嵌的 node 脚本（Playwright 抓取所有 periods × tabs）
# 由 fetch_all 动态生成，调用方传 periods + tabs + max_retries
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _normalize_period(period: str) -> str:
    """'2026-05' / '2026-5' → '2026-5'（源站不带前导 0）"""
    m = re.match(r'^(\d{4})-(\d{1,2})$', (period or '').strip())
    if not m:
        raise ValueError(f"无效 period 格式: {period!r}（期望 'YYYY-M' 或 'YYYY-MM'）")
    return f"{m.group(1)}-{int(m.group(2))}"


def _row_to_dict(row: dict) -> dict:
    """源站 row → 统一字段（clmc/ggxh/dw/price/remark + id/index）。
    
    源站原始字段：
        ggxh, clmc, isFirst, isThird, dw, isSecond, price, remark, id
    """
    return {
        'index': str(row.get('id') or ''),
        'clmc': (row.get('clmc') or '').strip(),
        'ggxh': (row.get('ggxh') or '').strip(),
        'dw': (row.get('dw') or '').strip(),
        'price': str(row.get('price') or '0').strip(),
        'remark': (row.get('remark') or '').strip(),
    }


# ── 内嵌的 node 抓取脚本（Playwright + 内部 fetch） ──
# 用占位符（避免与 JS 的 {} 冲突）
_FETCH_SCRIPT_TEMPLATE = '''\
const { chromium } = require('playwright');

const periods = __PERIODS__;
const tabs = __TABS__;
const endpoint = 'http://58.59.43.227:81/EpointSDRZ/rest/zjzmaterialpriceserver/getreleaseprice';
const pageSize = 2000;

(async () => {
  const browser = await chromium.launch({
    executablePath: '__CHROME_PATH__',
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
  });
  const page = await browser.newPage();
  
  // 1. 先访问 dist/ 初始化 SPA session
  await page.goto('http://58.59.43.227:81/dist/#/index/priceDissemination', {waitUntil: 'networkidle', timeout: 60000});
  await new Promise(r => setTimeout(r, 3500));
  
  // 2. 逐个 unit 抓取（page.evaluate 内部 fetch 用浏览器 session）
  for (const period of periods) {
    for (const tab of tabs) {
      try {
        const allRows = [];
        let pageIndex = 0;
        let totalCount = 0;
        while (true) {
          const result = await page.evaluate(async ([p, t, pi, ps]) => {
            const raw = JSON.stringify({params: JSON.stringify({
              pageIndex: pi, pageSize: ps, condition: '',
              periods: p, tabType: t, id: 'f9root'
            })});
            const resp = await fetch('http://58.59.43.227:81/EpointSDRZ/rest/zjzmaterialpriceserver/getreleaseprice', {
              method: 'POST',
              credentials: 'include',
              headers: {'Content-Type': 'application/x-www-form-urlencoded'},
              body: raw
            });
            const text = await resp.text();
            if (text === '{}') return {rows: [], totalCount: 0, empty: true};
            try {
              const data = JSON.parse(text);
              return {
                rows: data?.custom?.data?.data || [],
                totalCount: data?.custom?.data?.totalCount || 0,
                empty: false
              };
            } catch(e) { return {rows: [], totalCount: 0, err: e.message}; }
          }, [period, tab, pageIndex, pageSize]);
          
          if (result.err) {
            console.log(JSON.stringify({err: 'period=' + period + '/tab=' + tab + ': ' + result.err}));
            break;
          }
          allRows.push(...result.rows);
          totalCount = result.totalCount;
          if (result.empty || result.rows.length < pageSize) break;
          pageIndex++;
          if (pageIndex > 100) break;  // 安全防护
        }
        
        console.log(JSON.stringify({
          period: period, tab: tab,
          rows: allRows.length, totalCount: totalCount,
          data: allRows
        }));
      } catch (e) {
        console.log(JSON.stringify({err: 'period=' + period + '/tab=' + tab + ': ' + e.message}));
      }
    }
  }
  
  await browser.close();
})();
'''


def fetch_all(periods: List[str], tabs: List[str] = ('1', '2', '3'),
              max_retries: int = 2) -> Dict[Tuple[str, str], List[dict]]:
    """批量抓取多 period × 多 tab 的全量数据。

    一次浏览器启动，所有 unit 共享 session（v1.1 设计）。

    Args:
        periods: 业务期列表，如 ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05']
        tabs: tab 列表，默认 ('1', '2', '3')

    Returns:
        {(period_normalized, tab): [row, ...]} 字典
        period_normalized 是 'YYYY-M' 形式（无前导 0）

    Raises:
        RuntimeError: 所有重试均失败
    """
    # 规范化 periods
    norm_periods = [_normalize_period(p) for p in periods]
    # 生成 node 脚本（占位符替换，避免与 JS 的 {} 冲突）
    script = (
        _FETCH_SCRIPT_TEMPLATE
        .replace('__PERIODS__', json.dumps(norm_periods, ensure_ascii=False))
        .replace('__TABS__', json.dumps(list(tabs), ensure_ascii=False))
        .replace('__CHROME_PATH__', CHROME_PATH)
    )
    script_path = os.path.join(_SCRIPT_DIR, 'tmp', 'fetch_all_runner.js')
    os.makedirs(os.path.dirname(script_path), exist_ok=True)
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script)

    last_err = None
    for attempt in range(max_retries):
        try:
            proc = subprocess.run(
                ['node', script_path],
                capture_output=True, text=True,
                cwd=_SCRIPT_DIR,
                timeout=1800,
                env={**os.environ, 'PATH': os.environ.get('PATH', '')},
            )
            if proc.returncode != 0:
                raise RuntimeError(f"node 进程退出码 {proc.returncode}: {proc.stderr[-500:]}")

            # 解析 JSON Lines 输出
            result: Dict[Tuple[str, str], List[dict]] = {}
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if 'err' in obj:
                    print(f"  [!] {obj['err']}")
                    continue
                period = obj.get('period')
                tab = obj.get('tab')
                rows = obj.get('data', [])
                if period and tab:
                    result[(period, tab)] = [_row_to_dict(r) for r in rows]
            return result
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"fetch_all 失败（重试 {max_retries} 次）: {last_err}")


def fetch_one(period: str, tab_type: str, page_size: int = 2000) -> Tuple[List[dict], str]:
    """抓取单个 period × tab_type 的全量数据（包装 fetch_all）。

    Returns:
        (rows, normalized_period) 元组
    """
    result = fetch_all([period], [tab_type])
    np_ = _normalize_period(period)
    rows = result.get((np_, tab_type), [])
    return rows, np_


def get_current_period() -> str:
    """获取源站当前期（v1.1：返回当前年月）。"""
    from datetime import datetime
    return datetime.now().strftime('%Y-%m')


__all__ = [
    'ENDPOINT',
    'TAB_NAMES',
    'fetch_one',
    'fetch_all',
    'get_current_period',
]


# ── 自测 ──────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    periods = sys.argv[1:] or ['2026-05']
    print(f"[*] 抓取 periods={periods} tabs=['1','2','3']")
    result = fetch_all(periods)
    total_rows = 0
    for (p, t), rows in sorted(result.items()):
        print(f"  period={p} tab={t} ({TAB_NAMES.get(t, t)}): {len(rows)} rows")
        total_rows += len(rows)
    print(f"\n[i] 总计: {total_rows} rows")