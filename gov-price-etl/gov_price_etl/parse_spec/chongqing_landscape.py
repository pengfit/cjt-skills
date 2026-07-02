#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse_spec/chongqing_landscape.py - 园林景观专用规格解析

园林景观合成 spec 格式（cmd_write 拼出）：
  干径{X} 冠径{Y} 分枝高{Z}
  干径{X} 冠径{Y}
  高{X} 干径{Y} 冠径{Z}
  
X / Y / Z 可能是：
  - 区间值："7-9"、"200-220"
  - 大于值："大于200"、">200"
  - 特殊词："全冠"、"全干"
"""
import re

# 干径 / 冠径 / 分枝高 / 高
# 值匹配：'全冠' / '全干' 整体 OR 数字区间 / 大于 / 小于
_VAL = r'(全冠|全干|(?:\d+(?:\.\d+)?|[一二三四五六七八九十百零]+)\s*以上|(?:\d+(?:\.\d+)?|[一二三四五六七八九十百零]+)\s*以下|[\d\.]+(?:\s*[\-到至~]\s*\d+(?:\.\d+)?)?|大于\s*\d+(?:\.\d+)?|小于\s*\d+(?:\.\d+)?|>\s*\d+(?:\.\d+)?|<\s*\d+(?:\.\d+)?)'

_PATTERNS = [
    ('trunk_diameter',  rf'干径\s*({_VAL})'),
    ('crown_diameter',  rf'冠径\s*({_VAL})'),
    ('branch_height',   rf'分枝高\s*({_VAL})'),
    ('height',          rf'(?<!分枝)(?<![分干冠])高\s*({_VAL})'),
]


def _clean_val(s: str) -> str:
    return s.strip().rstrip(',，')


def parse_landscape_spec(spec: str) -> dict:
    """解析园林景观合成 spec。

    Args:
        spec: '干径7-9 冠径大于200 分枝高200-220'
    
    Returns:
        dict: {'trunk_diameter': '7-9cm', 'crown_diameter': '大于200cm', 'branch_height': '200-220cm'}
        特珠值如 '全冠' 直接返回 '全冠'（不加 cm 后缀）。
    """
    if not spec:
        return {}

    out = {}
    for key, pat in _PATTERNS:
        m = re.search(pat, spec)
        if m:
            val = _clean_val(m.group(1))
            if val:
                # 特珠值不加 cm
                if val in ('全冠', '全干'):
                    out[key] = val
                else:
                    out[key] = val + ('cm' if not val.endswith('cm') else '')
    return out
