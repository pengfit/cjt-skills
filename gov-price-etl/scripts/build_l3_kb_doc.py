#!/usr/bin/env python3
"""从 category_v3 + breed_l3_map_v3 自动生成 Dify KB 上传文档

输出: data/l3_kb_doc.md
每条 L3 一个 ### chunk, 含 L1/L2 上下文 + 实际品种例子
可直接上传 Dify 知识库
"""
import sqlite3
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB = PROJECT_ROOT / 'data' / 'category_v3_rules.db'
OUT = PROJECT_ROOT / 'data' / 'l3_kb_doc.md'

# L1 大类描述 (用于 KB 上下文)
L1_DESCS = {
    '01': '房屋建筑工程类，含土石方、地基、桩基、砌筑、混凝土及钢筋、'
          '金属结构、木结构、屋面防水、保温隔热防腐等',
    '02': '建筑装饰工程类，含楼地面、墙柱面、天棚、门窗、油漆涂料、'
          '其他装饰（柜类、扶手等）',
    '03': '安装工程-给排水类，含给水、排水、燃气、采暖管道、阀门、'
          '卫生洁具等',
    '04': '安装工程-电气类，含变压器、配电、母线、控制保护、电机、'
          '电缆、电线配管、防雷接地、照明灯具等',
    '05': '安装工程-暖通类，含通风管道、通风空调设备、采暖设备等',
    '06': '安装工程-智能化类，含综合布线、安防系统、消防报警等弱电系统',
    '07': '市政工程类，含道路、桥涵、管网等',
    '08': '园林景观类，含绿化苗木花卉、园建材料、景观小品等',
}

# L2 描述 (用于 KB 上下文)
L2_DESCS = {
    # L1 01
    '01.01': '土石方工程，挖填方',
    '01.02': '地基处理与边坡支护',
    '01.03': '桩基工程',
    '01.04': '砌筑工程',
    '01.05': '混凝土及钢筋混凝土工程，含现浇/预制构件、钢筋、螺栓铁件',
    '01.06': '金属结构工程，含钢网架、钢屋架、钢柱、钢梁、钢板、金属制品',
    '01.07': '木结构工程',
    '01.08': '屋面及防水工程，含瓦屋面、屋面防水、墙面楼地面防水',
    '01.09': '保温隔热防腐工程',
    # L1 02
    '02.01': '楼地面装饰工程',
    '02.02': '墙柱面装饰与隔断幕墙',
    '02.03': '天棚工程',
    '02.04': '门窗工程',
    '02.05': '油漆涂料裱糊工程',
    '02.06': '其他装饰工程',
    # L1 03
    '03.01': '给水管道',
    '03.02': '排水管道',
    '03.03': '燃气管道',
    '03.04': '采暖管道',
    '03.05': '阀门',
    '03.06': '卫生器具',
    # L1 04
    '04.01': '变压器安装',
    '04.02': '配电装置',
    '04.03': '母线安装',
    '04.04': '控制保护装置与开关插座',
    '04.05': '电机',
    '04.06': '电缆',
    '04.07': '电线与电气配管',
    '04.08': '防雷及接地装置',
    '04.09': '照明器具',
    # L1 05
    '05.01': '通风管道',
    '05.02': '通风空调设备',
    '05.03': '采暖设备',
    # L1 06
    '06.01': '综合布线',
    '06.02': '安防系统',
    '06.03': '消防报警',
    # L1 07
    '07.01': '道路工程',
    '07.02': '桥涵工程',
    '07.03': '管网工程',
    # L1 08
    '08.01': '绿化工程（苗木花卉草坪等）',
    '08.02': '园建工程',
    '08.03': '小品水景',
}


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # 1) 全部 L3 (按 L1/L2/L3 排序)
    l3_rows = cur.execute('''
        SELECT DISTINCT l1, l2, l3, name_l1, name_l2, name_l3
        FROM category_v3
        WHERE l3 IS NOT NULL AND l3 != ''
        ORDER BY l1, l2, l3
    ''').fetchall()

    # 2) 品种映射 (按 l3 聚合, 取高置信度, 限 8 个)
    breed_by_l3 = defaultdict(list)
    for r in cur.execute('''
        SELECT m.breed_clean, m.l3, m.confidence, m.source
        FROM breed_l3_map_v3 m
        WHERE m.l3 IS NOT NULL AND m.l3 != '' AND m.l3 != '其他'
        ORDER BY m.confidence DESC
    ''').fetchall():
        breed_by_l3[r[1]].append(r)

    # 3) 渲染 markdown
    lines = []
    lines.append('# GB 50500 工程量清单规范 - v3 分类体系 知识库')
    lines.append('')
    lines.append('> **用途**：材料品种 → L3 分类编码 语义检索（配合 Dify workflow 使用）')
    lines.append('> **规模**：8 个 L1 / 42 个 L2 / 145 个 L3 / {} 条已映射品种'.format(
        sum(len(v) for v in breed_by_l3.values())))
    lines.append('> **来源**：GB 50854-2013 / GB/T 50856-2024 / GB 50857-2013 / GB 50858-2013')
    lines.append('')
    lines.append('## 检索说明')
    lines.append('')
    lines.append('- 每条 L3 是一个独立 chunk，含 L1/L2 上下文 + 名称 + 实际品种例子')
    lines.append('- 检索时输入材料品种名（如 "冷轧带肋钢筋"、"XPS"），返回最相关的 top-K L3')
    lines.append('- L3 编码格式 `XX.XX.XX`（如 01.05.15 钢筋工程）')
    lines.append('')

    # 按 L1/L2 分组
    l1_groups = defaultdict(lambda: defaultdict(list))
    for r in l3_rows:
        l1, l2, l3, n1, n2, n3 = r
        l1_groups[l1][l2].append((l3, n1, n2, n3))

    for l1 in sorted(l1_groups.keys()):
        # L1 标题
        first = l1_groups[l1][list(l1_groups[l1].keys())[0]][0]
        l1_name = first[1]  # name_l1
        lines.append('---')
        lines.append('')
        lines.append(f'## L1 {l1} {l1_name}')
        lines.append('')
        if l1 in L1_DESCS:
            lines.append(L1_DESCS[l1])
            lines.append('')

        for l2 in sorted(l1_groups[l1].keys()):
            # L2 标题
            first_l2 = l1_groups[l1][l2][0]
            l2_name = first_l2[2]
            lines.append(f'### L2 {l2} {l2_name}')
            lines.append('')
            if l2 in L2_DESCS:
                lines.append(L2_DESCS[l2])
                lines.append('')

            for l3, n1, n2, n3 in l1_groups[l1][l2]:
                # L3 chunk (这是 Dify KB 索引的主要单位)
                lines.append(f'#### L3 {l3} {n3}')
                lines.append('')
                lines.append(f'**L3 编码**：`{l3}`')
                lines.append('')
                lines.append(f'**分类路径**：L1 {l1} {n1} → L2 {l2} {n2} → L3 {l3} {n3}')
                lines.append('')

                # 实际品种例子
                examples = breed_by_l3.get(l3, [])
                if examples:
                    lines.append('**常见品种**（来自已积累映射）：')
                    for breed, l3_, conf, src in examples[:8]:
                        src_label = {
                            'ai_v3': 'AI',
                            'pattern_v3': '本地',
                            'db_exact_v3': '本地',
                            'db_fuzzy_v3': '本地',
                            'no_match_v3': '本地',
                            'ai_fallback_v3': 'AI',
                        }.get(src, src)
                        lines.append(f'- `{breed}`（置信 {conf:.2f}，{src_label}）')
                    lines.append('')

    # 附录: 全部 L3 速查表
    lines.append('---')
    lines.append('')
    lines.append('## 附录: 全部 L3 速查表')
    lines.append('')
    lines.append('| L3 编码 | L1 | L2 | L3 名称 | 映射品种数 |')
    lines.append('|---|---|---|---|---|')
    for l1, l2, l3, n1, n2, n3 in l3_rows:
        cnt = len(breed_by_l3.get(l3, []))
        lines.append(f'| `{l3}` | {n1} | {n2} | {n3} | {cnt} |')
    lines.append('')

    # 写文件
    content = '\n'.join(lines)
    OUT.write_text(content, encoding='utf-8')

    # 统计
    size_kb = OUT.stat().st_size / 1024
    print(f'生成 {OUT}')
    print(f'  字节: {OUT.stat().st_size} ({size_kb:.1f} KB)')
    print(f'  L1: {len(l1_groups)} 个')
    print(f'  L3 chunk: {len(l3_rows)} 个')
    print(f'  品种例子: {sum(len(v) for v in breed_by_l3.values())} 条 (覆盖 {len(breed_by_l3)} 个 L3)')

    conn.close()


if __name__ == '__main__':
    main()
