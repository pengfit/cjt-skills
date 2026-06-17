#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classify 常量

集中管理分类模块的阈值/常量，避免散落各处。
"""

# 品种映射最低入库置信度：低于此值的 AI 推断结果不写入 breed_l3_map，
# 也不参与 stage 1 (精确) / stage 2 (Jaccard 模糊) 召回候选。
# 防御性过滤：手动塞入 DB 的低 conf 行也不会被命中。
MIN_RULE_CONFIDENCE = 0.90
