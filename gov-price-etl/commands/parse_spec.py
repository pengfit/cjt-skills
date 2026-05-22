"""parse_spec.py - 规格字段解析器

将复合规格字符串拆分为结构化字段：
  - thickness, length, width, height (尺寸)
  - diameter, ring_stiffness, pressure (管材)
  - material, color (材质/颜色)
  - grade (牌号/强度等级)
  - voltage, current (电气)
  - cross_section (电缆截面)
  - asphalt_type, cement_content (沥青/水泥)
  - channels, doors, cores (设备)
  - fiber_core, length_range (光纤/跳线)
  - media, range, cable_length, output (变送器)
  - temp_range, humidity_range (温湿度)
"""

import re


def parse_spec(spec: str) -> dict:
    if not spec or spec == "/" or spec == "":
        return {}

    s = spec.strip().replace("\u00d7", "*")
    s = re.sub(r"\s+", " ", s).strip()

    result = {}

    # 1. 厚度
    m = re.search(r"厚度[:：]?\s*(\d+\.?\d*)\s*mm", s, re.IGNORECASE)
    if m:
        result["thickness"] = m.group(1) + "mm"

    # 2. 电缆截面（仅限电线电缆关键词，且含 mm2/mm²）— 必须在 3D 尺寸之前
    cable_kws = ["YJV", "BV", "WDZ", "ZR", "NH", "RV", "KV", "RYS", "WDZN"]
    # 同时匹配 ASCII mm2 和 Unicode mm² (U+00B2 或 U+178)
    mm2_pattern = re.compile(r"mm2|mm\xb2|mm\u00b2|mm²", re.IGNORECASE)
    if any(kw in s for kw in cable_kws) and mm2_pattern.search(s):
        segs = s.split("+")
        # 优先：从不含 mm2 的段找 N×N（如 YJV-3×240+1×120mm2 → cores=3, cross_section=240mm²）
        for seg in segs:
            if not mm2_pattern.search(seg):
                m = re.search(r"(\d+)\s*[×xX*]\s*(\d+(?:\.\d+)?)", seg, re.IGNORECASE)
                if m and int(m.group(1)) > 1:
                    result["cores"] = m.group(1) + "芯"
                    result["cross_section"] = m.group(2) + "mm²"
                    break
        # 次从含 mm2 的段找（如 1×120mm2 → 120mm²）
        if "cross_section" not in result:
            for seg in segs:
                if mm2_pattern.search(seg):
                    # 先试 N×截面：YJV-3×2.5mm2 → cores=3, cross_section=2.5mm²
                    m2 = re.search(r"(\d+)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(?:mm2|mm\xb2|mm\u00b2|mm²)", seg, re.IGNORECASE)
                    if m2:
                        result["cores"] = m2.group(1) + "芯"
                        result["cross_section"] = m2.group(2) + "mm²"
                        break
                    # 纯截面：BV-10mm2 → cross_section=10mm²
                    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm2|mm\xb2|mm\u00b2|mm²)", seg, re.IGNORECASE)
                    if m:
                        result["cross_section"] = m.group(1) + "mm²"
                        break

    # 3. 3D 尺寸 AxBxCmm（仅匹配 mm 后无数字/字母的，避免 mm2 干扰）
    m = re.search(r"(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+\.?\d*)\s*mm(?![a-z0-9])", s, re.IGNORECASE)
    if m:
        result["length"] = m.group(1) + "mm"
        result["width"] = m.group(2) + "mm"
        result["height"] = m.group(3) + "mm"
    else:
        # 3a. 2D 尺寸: 330×600mm (瓷砖)
        m = re.search(r"(\d+)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*mm(?![a-z0-9])", s, re.IGNORECASE)
        if m:
            result["length"] = m.group(1) + "mm"
            result["width"] = m.group(2) + "mm"
        else:
            # 3b. 配电箱/设备外形尺寸: 300×200×100mm 或 300×200mm（无 mm 后缀）
            m = re.search(r"(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+)(?:mm)?", s, re.IGNORECASE)
            if m:
                result["length"] = m.group(1) + "mm"
                result["width"] = m.group(2) + "mm"
                result["height"] = m.group(3) + "mm"
            else:
                m = re.search(r"(\d+)\s*[×xX*]\s*(\d+)\s*mm(?![a-z0-9])", s, re.IGNORECASE)
                if m:
                    result["length"] = m.group(1) + "mm"
                    result["width"] = m.group(2) + "mm"

    # 4. 管径: DN125~250, PN1.6DN150, D325+, Φ600
    m = re.search(r"(DN\s*\d+(?:\s*~\s*\d+)?)", s)
    if m:
        result["diameter"] = m.group(1).strip()
    else:
        m = re.search(r"(?:^|[^A-Z\u03A6\u03C6])\s*[D\u03A6\u03C6]\s*(\d+)", s)
        if m:
            result["diameter"] = m.group(1).strip()

    # 5. 环刚度: SN8, SN10, SN12.5
    m = re.search(r"SN(\d+\.?\d*)", s, re.IGNORECASE)
    if m:
        result["ring_stiffness"] = "SN" + m.group(1)

    # 6. 压力等级: PN1.6, PN1.0
    m = re.search(r"PN(\d+\.?\d*)", s, re.IGNORECASE)
    if m:
        result["pressure"] = "PN" + m.group(1)

    # 7. 材质: PE, PVC, PPR, PP, PB, 铸铁, 钢, 不锈钢, 铜, 铝合金
    material_kws = ["PE", "PVC", "PPR", "PP", "PB", "铸铁", "钢", "不锈钢", "铜", "铝合金", "镀锌", "树脂", "橡胶"]
    for kw in material_kws:
        if kw in s:
            result["material"] = kw
            break

    # 7a. 表面处理/涂层工艺（优先级低于材质关键字，避免冲突）
    surface_kws = {
        "氟碳喷涂": "氟碳喷涂", "木纹转印": "木纹转印", "烤漆": "烤漆",
        "粉末喷涂": "粉末喷涂", "覆膜": "覆膜", "喷涂": "喷涂",
        "氟碳": "氟碳", "转印": "转印",
    }
    for kw, val in surface_kws.items():
        if kw in s:
            result["surface"] = val
            break

    # 7b. 产品系列: 85系列, 70系列, 100系列
    m = re.search(r"(\d+)\s*系列", s)
    if m:
        result["series"] = m.group(1) + "系列"

    # 8. 颜色: 白, 黑, 红, 蓝, 绿, 黄, 灰, 米色
    color_kws = ["白色", "黑色", "红色", "蓝色", "绿色", "黄色", "灰色", "米色", "透明", "银色"]
    for kw in color_kws:
        if kw in s:
            result["color"] = kw
            break

    # 9. 牌号/等级
    cement_grades = ["P.O42.5", "P.O42.5R", "P.O52.5", "P.O52.5R", "P.II42.5", "P.II52.5"]
    for g in cement_grades:
        if g in s:
            result["grade"] = g
            break
    if "grade" not in result:
        # 混凝土强度等级: C30, C35, C40, C45, C50
        m = re.search(r"(?<![a-zA-Z0-9])C(\d+)\b", s)
        if m:
            result["grade"] = "C" + m.group(1)
    if "grade" not in result:
        # 沥青混凝土: SBSAC-13, AC-13
        m = re.search(r"(SBS)?AC-?(\d+)", s, re.IGNORECASE)
        if m:
            result["asphalt_type"] = m.group(0).upper()
    if "grade" not in result:
        # 水泥含量: 水泥含量5%
        m = re.search(r"水泥含量(\d+)%", s)
        if m:
            result["cement_content"] = m.group(1) + "%"
    if "grade" not in result:
        # H型钢高度范围: H100~H250, H100~250, H200
        m = re.search(r"H(\d+)\s*~\s*(?:H)?(\d+)", s, re.IGNORECASE)
        if m:
            result["height_range"] = f"H{m.group(1)}~H{m.group(2)}"
            # 单独 H200 也算高度标记
            m2 = re.search(r"(?<![a-zA-Z0-9])H(\d{3})\b", s)
            if m2 and not result.get("height_range"):
                result["height_range"] = f"H{m2.group(1)}"
    if "grade" not in result:
        # 通用等级牌号
        m = re.search(r"\b(D?Q235|Q345|HRB335|HRB400|HPB300)\b", s, re.IGNORECASE)
        if m:
            result["grade"] = m.group(1).upper()
    if "grade" not in result:
        # 钢材等级（全牌号含屈服强度后缀）: Q235B, Q345B, Q390B, Q420B, Q460B
        # (?<![a-zA-Z]) 确保 Q 前不是字母（允许数字如 H250Q235B），不加 \b 结尾保证连续匹配
        m = re.search(r"(?<![a-zA-Z])Q\d{3}[A-Z]", s, re.IGNORECASE)
        if m:
            result["grade"] = m.group(0).upper()
    if "grade" not in result:
        # 防火门等级: 甲级, 乙级, 丙级, 丁级
        fire_grade_kws = {
            "甲级": "甲级", "乙级": "乙级", "丙级": "丙级", "丁级": "丁级",
        }
        for kw, val in fire_grade_kws.items():
            if kw in s:
                result["fire_rating"] = val
                break

    # 10. 电压等级: 250V, 220V, 380V（也处理 250V10A 复合型）
    m = re.search(r"(\d+)\s*[VVA](?:\d+)?\s*[A]?\s*A\b", s)
    if not m:
        m = re.search(r"(\d+)\s*[VVA]", s)
    if m:
        val = m.group(1)
        if int(val) >= 220 and int(val) <= 400:
            result["voltage"] = val + "V"
    m = re.search(r"电压\s*(\d+)", s)
    if m:
        result["voltage"] = m.group(1) + "V"
    # 电压后紧跟电流: 250V10A
    m = re.search(r"(\d+)\s*[VVA]\s*(\d+)\s*A\b", s)
    if m:
        result["voltage"] = m.group(1) + "V"
        result["current"] = m.group(2) + "A"

    # 11. 电流: 10A, 16A, 630A
    m = re.search(r"(\d+)\s*A\b", s)
    if m and "voltage" not in result:
        result["current"] = m.group(1) + "A"
    m = re.search(r"电流\s*(\d+)", s)
    if m:
        result["current"] = m.group(1) + "A"

    # 12. 设备规格: 8路, 4门, 2门, N芯
    m = re.search(r"(\d+)\s*路", s)
    if m:
        result["channels"] = m.group(1) + "路"
    m = re.search(r"(\d+)\s*门", s)
    if m:
        result["doors"] = m.group(1) + "门"
    m = re.search(r"(\d+)\s*芯", s)
    if m:
        result["cores"] = m.group(1) + "芯"

    # 13. 光纤规格: 芯直径:9/125μm
    m = re.search(r"芯直径:(\d+/\d+)(?:μm)?", s, re.IGNORECASE)
    if m:
        result["fiber_core"] = m.group(1)

    # 14. 跳线/线缆长度: 2～4米, 长度50cm, 10m, 1.0~3.0cm
    if "length" not in result:
        # 带单位的范围值: 1.0~3.0cm, 2.0~4.0m, 0.5~1.5cm
        m = re.search(r"(\d+\.?\d*)\s*[～~]\s*(\d+\.?\d*)\s*(cm|m|厘米|米)", s)
        if m:
            result["length_range"] = m.group(1) + "~" + m.group(2) + m.group(3)
        else:
            m = re.search(r"(\d+)\s*[～~]\s*(\d+)\s*米", s)
            if m:
                result["length_range"] = m.group(1) + "~" + m.group(2) + "m"
        m = re.search(r"长度(\d+)cm", s, re.IGNORECASE)
        if m:
            result["length"] = m.group(1) + "cm"
        # 长度前缀: 长度1500（无单位，默认mm）
        if "length" not in result:
            m = re.search(r"长度(\d+)", s)
            if m:
                result["length"] = m.group(1) + "mm"
        # 高度前缀: 高100mm, 高500
        if "height" not in result:
            m = re.search(r"高(\d+)\s*mm", s, re.IGNORECASE)
            if m:
                result["height"] = m.group(1) + "mm"
            else:
                m = re.search(r"高(\d+)", s)
                if m:
                    result["height"] = m.group(1) + "mm"
        if "length" not in result and "length_range" not in result:
            m = re.search(r"(?<![0-9.~～\d])\s*(\d+)m(?!m)(?![a-zA-Z])", s)
            if m:
                result["length"] = m.group(1) + "m"

    # 14a. 温度+尺寸复合型: 70℃800*800（温度在前，尺寸在后）
    if "temperature" not in result and not result.get("length"):
        m = re.search(r"(\d+)\s*℃(\d+)", s)
        if m:
            result["temperature"] = m.group(1) + "℃"
            # 剩余部分当作尺寸处理
            remaining = s[s.index(m.group(0)) + len(m.group(0)):].strip()
            # 尝试解析后续的尺寸
            m2 = re.search(r"(\d+)\s*[×xX*]\s*(\d+)", remaining)
            if m2:
                result["length"] = m2.group(1) + "mm"
                result["width"] = m2.group(2) + "mm"

    # 15. 液位变送器规格: 介质:水, 量程:0~1.8m, 电缆长度L=2.5m, 输出:4~20mA
    m = re.search(r"介质[:：]([^,，]+)", s)
    if m:
        result["media"] = m.group(1).strip()
    m = re.search(r"量程[:：]?(\S+)", s)
    if m:
        result["range"] = m.group(1).strip()
    m = re.search(r"电缆长度L=(\S+)", s, re.IGNORECASE)
    if m:
        result["cable_length"] = m.group(1).strip()
    m = re.search(r"输出[:：]([^,，]+)", s)
    if m:
        result["output"] = m.group(1).strip()

    # 16. 温湿度范围: 温度:-10℃～50℃, 湿度:0～100%RH
    m = re.search(r"温度[:：]?-?(\d+)℃～(\d+)℃", s, re.IGNORECASE)
    if m:
        result["temp_range"] = m.group(1) + "℃~" + m.group(2) + "℃"
    m = re.search(r"湿度[:：]?(\d+)～(\d+)%RH", s, re.IGNORECASE)
    if m:
        result["humidity_range"] = m.group(1) + "%~" + m.group(2) + "%RH"

    # 高度前缀: 高100mm, 高500, 80-350mm高（高度范围）
    if "height" not in result and not result.get("length_range"):
        m = re.search(r"(\d+(?:\s*[~-]\s*\d+)?)\s*mm\s*高", s)
        if m:
            val = m.group(1).strip()
            if "~" in val or "-" in val:
                result["height_range"] = val.replace(" ", "") + "mm"
            else:
                result["height"] = val + "mm"
        else:
            m = re.search(r"高(\d+)\s*mm", s, re.IGNORECASE)
            if m:
                result["height"] = m.group(1) + "mm"
            else:
                m = re.search(r"高(\d+)", s)
                if m:
                    result["height"] = m.group(1) + "mm"
                else:
                    # H=0.36m, H=600, H=800 (井筒/散热器高度，支持小数)
                    m = re.search(r"H\s*=\s*([\d.]+)\s*m", s, re.IGNORECASE)
                    if m:
                        val = m.group(1)
                        if "." in val:
                            # 小数米转mm: 0.36m → 360mm
                            result["height"] = str(int(float(val) * 1000)) + "mm"
                        else:
                            result["height"] = val + "mm"
                    else:
                        m = re.search(r"H\s*=\s*(\d+)", s, re.IGNORECASE)
                        if m:
                            result["height"] = m.group(1) + "mm"

    # 厚度前缀: 厚:2.5mm, 厚2.5mm（兼容厚度:）
    if not result.get("thickness"):
        m = re.search(r"厚[:：]?\s*(\d+\.?\d*)\s*mm", s, re.IGNORECASE)
        if m:
            result["thickness"] = m.group(1) + "mm"

    # 厚度后缀: 0.6mm厚（条形0.6mm厚 → thickness=0.6mm）
    if not result.get("thickness"):
        m = re.search(r"(\d+\.?\d*)\s*mm\s*厚$", s, re.IGNORECASE)
        if m:
            result["thickness"] = m.group(1) + "mm"

    # 钢格栅/钢格盖板编号: G755/40/100, G455/30/100 → grade 字段
    if not result:
        m = re.search(r"\bG\d{3}/\d+/\d+\b", s)
        if m:
            result["grade"] = m.group(0)

    # 门型号: M2蜂窝板门, M1022 → designation 字段（暂用 grade 暂存）
    if not result:
        m = re.search(r"\bM\d+\S*", s)
        if m:
            result["grade"] = m.group(0)

    # 17. δ厚度标记: δ4, δ6（希腊字母 Delta 表示厚度）
    if not result.get("thickness"):
        m = re.search(r"δ(\d+\.?\d*)\s*$", s)
        if m:
            result["thickness"] = m.group(1) + "mm"
        else:
            # δ=4.5 或 δ=3.5（等号形式）
            m = re.search(r"δ\s*=\s*(\d+\.?\d*)", s)
            if m:
                result["thickness"] = m.group(1) + "mm"

    # 17b. 铸铁/钢制散热器高度: 双柱H=800, 四柱H=600（无空格）
    if not result.get("height"):
        m = re.search(r"(?:双|四|单)柱H=(\d+)", s)
        if m:
            result["height"] = m.group(1) + "mm"

    # 17c. 多叶风口/排烟口 W*(H1+H2) 复合尺寸: 400*(800+250) → width=400, height=总高
    # 格式: 宽*(前高+后高)，总高 = H1 + H2
    if not result.get("width") and not result.get("length"):
        m = re.search(r"^(\d{3,4})\s*\*\s*\((\d+)\s*\+\s*(\d+)\)", s)
        if m:
            result["width"] = m.group(1) + "mm"
            total_h = int(m.group(2)) + int(m.group(3))
            result["height"] = str(total_h) + "mm"

    # 17d. 温度+外形尺寸复合型: 70℃外形尺寸≤750*750 或 70℃外形尺寸≤750×750
    # 提取温度（℃，不含℃的在前）和尺寸（≤750*750 形式）
    if not result.get("temperature"):
        m = re.search(r"(\d+)\s*℃\s*外形尺寸[≤≤≤]\s*(\d+)\s*[×xX*]\s*(\d+)", s)
        if m:
            result["temperature"] = m.group(1) + "℃"
            result["length"] = m.group(2) + "mm"
            result["width"] = m.group(3) + "mm"

    # 18. 纯厚度 fallback：前面尺寸都没匹配到，且非 mm2 → 当作厚度
    if not result.get("length") and not result.get("thickness"):
        m = re.search(r"^(\d+\.?\d*)\s*mm$", s, re.IGNORECASE)
        if m:
            result["thickness"] = m.group(1) + "mm"

    # 18b2. 面板/开关插座 规格类型: 86型, 118型, 120型
    if not result.get("form"):
        form_kws = ["86型", "118型", "120型", "146型"]
        for kw in form_kws:
            if kw in s:
                result["form"] = kw
                break

    # 18b. 陶瓷洗脸盆/坐便器 安装类型: 台下盆, 台上盆, 立柱盆, 壁挂式
    if not result.get("installation_type"):
        install_kws = ["台下盆", "台上盆", "立柱盆", "壁挂式", "挂墙式", "半嵌盆"]
        for kw in install_kws:
            if kw in s:
                result["installation_type"] = kw
                break

    # 18c. 洁具排水类型: 下出水, 后进水地排水, 地排水, 侧排水, 后进后出
    if not result.get("drain_type"):
        drain_kws = ["下出水", "后进水地排水", "地排水", "侧排水", "后进后出", "后进前出"]
        for kw in drain_kws:
            if kw in s:
                result["drain_type"] = kw
                break

    # 18d. 洁具进水类型: 后进水, 侧进水, 上进水（"后进后出"归为排水类型，不归入进水）
    if not result.get("inlet_type"):
        inlet_kws = ["后进水", "侧进水", "上进水"]
        for kw in inlet_kws:
            if kw in s:
                result["inlet_type"] = kw
                break

    # 19. 无单位尺寸 AxB（无 mm 后缀，如 1200*400, 1600*800）
    if not result.get("length") and not result.get("thickness"):
        m = re.search(r"^(\d{3,4})\s*[×xX*]\s*(\d{3,4})(?:\s|$)", s)
        if m:
            result["length"] = m.group(1) + "mm"
            result["width"] = m.group(2) + "mm"

    return result


def clean_spec(spec: str) -> str:
    """清理规格字符串，用于 breed/breed_clean"""
    if not spec or spec == "/" or spec == "":
        return "/"
    s = spec.strip().replace("\u00d7", "*")
    s = re.sub(r"\s+", " ", s).strip()
    return s