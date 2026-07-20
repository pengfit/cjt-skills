"""check_status.py - 各城市 check.py 写 dashboard status 的公共 helper

v0.8.1（2026-07-03）新增。

背景：
- `/api/stats/check-status` 是 dashboard `/sync` 顶部「定时检查状态」
  chip 的数据源，从 `/tmp/gov-check-status/<key>.json` 读文件。
- chongqing v0.8 与 hainan v0.8.1 各有自己内联的 _write_check_status()。
- 剩 15 个城市的 check.py 只 print 到 stdout，dashboard 显示 pending。

本模块提供统一实现：
  - write_status(key, label, status, ...) —— 直接传状态值
  - write_status_from_check_output(key, label, output) —— 从已有 stdout 解析

字段格式必须与 chongqing / hainan 一致（dashboard API 透传给前端）。
"""
from __future__ import annotations

import datetime
import json
import os
import time
from typing import Optional

STATUS_DIR = os.environ.get("GOV_CHECK_STATUS_DIR", "/tmp/gov-check-status")


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def write_status(
    key: str,
    label: str,
    *,
    status: str,                    # 'ok' | 'update' | 'error' | 'pending'
    message: str = "",
    has_update: Optional[bool] = None,
    site_period: str = "",
    site_year: str = "",
    site_month: str = "",
    site_publish_date: str = "",
    es_period: str = "",
    es_update_date: str = "",
    extra: Optional[dict] = None,
) -> str:
    """写 /tmp/gov-check-status/<key>.json。返回写入的文件路径。"""
    if has_update is None:
        has_update = (status == "update")

    doc = {
        "city": key,
        "label": label,
        "status": status,
        "output": message,
        "time": _now_str(),
        "has_update": has_update,
        "site_latest_period": site_period,
        "site_latest_year": site_year,
        "site_latest_month": site_month,
        "site_latest_publish_date": site_publish_date,
        "es_latest_period": es_period,
        "es_latest_update_date": es_update_date,
    }
    if extra:
        doc.update(extra)

    os.makedirs(STATUS_DIR, exist_ok=True)
    fpath = os.path.join(STATUS_DIR, f"{key}.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return fpath


def write_status_from_check_output(
    key: str,
    label: str,
    output_text: str,
    *,
    city_label: Optional[str] = None,
) -> str:
    """从 check.py 输出的 stdout 文本推断状态，写 json。

    解析规则（覆盖 17 个城市 check.py 的输出格式）：
      - 提取以 `[<city_label>]` 开头的行（默认 city_label = label）
      - 出现下列关键字判定状态（最后一个匹配的胜出）：
          '✅' / '无新数据' / '已同步' / '已对齐'          → ok
          '🔔' / '有更新' / '需同步' / '需首次同步' / '缺月' → update
          '⚠️' / '异常' / '查询失败'                         → error
        默认 pending

    Args:
        key: 城市 key（小写，匹配 skill_registry / skill.yml，例如 'henan'）
        label: 城市中文 label，与 dashboard 显示一致
        output_text: check.py 的 stdout
        city_label: 城市在 stdout 中的标签（'河南'/'Henan'等），默认用 label

    Returns:
        写入的文件路径
    """
    city_label = city_label or label
    lines = (output_text or "").strip().split("\n")
    city_lines = [l for l in lines if l.startswith(f"[{city_label}]")]

    status = "pending"
    message = ""
    has_update = False

    for line in city_lines:
        if any(k in line for k in ["⚠️", "异常", "查询失败"]):
            status = "error"
            has_update = False
            message = line
        elif any(k in line for k in ["🔔", "有更新", "需同步", "需首次同步", "缺月", "有待同步", "待入仓"]):
            status = "update"
            has_update = True
            message = line
        elif any(k in line for k in ["✅", "无新数据", "已同步", "已对齐"]):
            status = "ok"
            has_update = False
            message = line

    if not message and city_lines:
        message = city_lines[-1]

    return write_status(
        key, label,
        status=status,
        message=message,
        has_update=has_update,
    )


# ── 与 chongqing / hainan _write_check_status 兼容的旧接口 ────────────

def write_status_chongqing_style(
    key: str,
    label: str,
    site_period: str,
    site_year: str,
    site_month: str,
    es_period: str,
    es_create_time: str,
    status: str,
    message: str,
) -> str:
    """兼容 chongqing v0.8 的 7 参调用风格。直接转 write_status()。"""
    return write_status(
        key, label,
        status=status,
        message=message,
        site_period=f"{site_year}年{site_month}" if site_year and site_month else site_period,
        site_year=site_year,
        site_month=site_month,
        es_period=es_period,
        es_update_date=es_create_time,
    )


__all__ = [
    "STATUS_DIR",
    "write_status",
    "write_status_from_check_output",
    "write_status_chongqing_style",
]
