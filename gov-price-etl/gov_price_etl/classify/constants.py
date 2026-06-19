#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classify 常量

集中管理分类模块的阈值/常量，避免散落各处。
"""

# 品种映射最低入库置信度：低于此值的 AI 推断结果不写入 breed_l3_map，
# 也不参与 stage 1 (精确) / stage 2 (Jaccard 模糊) 召回候选。
# 防御性过滤：手动塞入 DB 的低 conf 行也不会被命中。
MIN_RULE_CONFIDENCE = 0.80  # AI v3 分类置信度在 0.85 左右，需低于此值才能进入 stage 1 db_exact 匹配
