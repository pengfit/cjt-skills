"""parse_spec/base.py - 通用规格解析基类

各城市 parse_spec 均继承此类，覆盖城市特有规则（_city_rules）即可。
"""
import re


class BaseParseSpec:
    """规格解析基类，包含所有通用解析规则"""

    def parse(self, spec: str) -> dict:
        """解析规格字符串，返回 attr 字段字典"""
        if not spec or spec == "/" or spec == "":
            return {}

        s = spec.strip().replace("\u00d7", "*")
        s = re.sub(r"\s+", " ", s).strip()

        result = {}

        # 1. 厚度
        m = re.search(r"厚度[:：]?\s*(\d+\.?\d*)\s*mm", s, re.IGNORECASE)
        if m:
            result["thickness"] = m.group(1) + "mm"

        # 2. 电缆截面（仅限电线电缆关键词，且含 mm2/mm²）
        cable_kws = ["YJV", "BV", "WDZ", "ZR", "NH", "RV", "KV", "RYS", "WDZN"]
        mm2_pattern = re.compile(r"mm2|mm\xb2|mm\u00b2|mm²", re.IGNORECASE)
        if any(kw in s for kw in cable_kws) and mm2_pattern.search(s):
            segs = s.split("+")
            for seg in segs:
                if not mm2_pattern.search(seg):
                    m = re.search(r"(\d+)\s*[×xX*]\s*(\d+(?:\.\d+)?)", seg, re.IGNORECASE)
                    if m and int(m.group(1)) > 1:
                        result["cores"] = m.group(1) + "芯"
                        result["cross_section"] = m.group(2) + "mm²"
                        break
            if "cross_section" not in result:
                for seg in segs:
                    if mm2_pattern.search(seg):
                        m2 = re.search(r"(\d+)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(?:mm2|mm\xb2|mm\u00b2|mm²)", seg, re.IGNORECASE)
                        if m2:
                            result["cores"] = m2.group(1) + "芯"
                            result["cross_section"] = m2.group(2) + "mm²"
                            break
                        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm2|mm\xb2|mm\u00b2|mm²)", seg, re.IGNORECASE)
                        if m:
                            result["cross_section"] = m.group(1) + "mm²"

        # 3. 3D 尺寸 AxBxCmm（仅匹配 mm 后无数字/字母的）
        # ── 自动生成: 数值范围，表示从多少到多少毫米 ──
        m = re.search(r'(\d+)mm~(\d+)mm', s)
        if m:
            result['length_range'] = m.group(1) + '~' + m.group(2) + 'mm'
        m = re.search(r"^(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+)\s*mm\b", s, re.IGNORECASE)
        if m:
            result["length"] = m.group(1) + "mm"
            result["width"] = m.group(2) + "mm"
            result["thickness"] = m.group(3) + "mm"
        else:
            m = re.search(r"^(\d+)\s*[×xX*]\s*(\d+)\s*mm\b", s, re.IGNORECASE)
            if m:
                result["length"] = m.group(1) + "mm"
                result["width"] = m.group(2) + "mm"
            else:
                m = re.search(r"^(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+)\s*mm\b", s, re.IGNORECASE)
                if m:
                    result["length"] = m.group(1) + "mm"
                    result["width"] = m.group(2) + "mm"
                    result["thickness"] = m.group(3) + "mm"

        # 4. 钢管规格 D325*8*6000 → diameter=D325, thickness=8mm, length=6000mm
        if not result.get("diameter"):
            m = re.search(r"^D(\d+)\*(\d+)\*(\d+)\s*$", s)
            if m:
                result["diameter"] = "D" + m.group(1)
                result["thickness"] = m.group(2) + "mm"
                result["length"] = m.group(3) + "mm"

        # 4. 管径: DN125~250, D325+, Φ600
        if not result.get("diameter"):
            m = re.search(r"\b(DN\s*)(\d+)\s*~(?:\s*DN)?(\d+)", s, re.IGNORECASE)
            if m:
                result["diameter"] = "DN" + m.group(2) + "~" + m.group(3)
        if not result.get("diameter"):
            m = re.search(r"\bD\s*(\d+)\s*\+", s)
            if m:
                result["diameter"] = "D" + m.group(1)
        # 注意: Φ 相关口径已由 4e/4f/4g 接管，此处不再单独处理
        # 4b. SS型/器壁口径: SS100-1.6, GQQ100/2.5-PAVLN → DN100
        # 区分：不带分隔符的 SS304/SS316 是材质牌号（step14g 处理），
        # 带 - 或 / 的 SS100-1.6 是阀体型号/管径
        if not result.get("diameter"):
            m = re.search(r"\b(SS|GQQ|GQS|SQ|SQB)\s*(\d{1,3})(?=[-/])", s, re.IGNORECASE)
            if m:
                result["diameter"] = "DN" + m.group(2)
            elif re.search(r"\b(SS|GQQ|GQS|SQ|SQB)\s*(\d{1,2})\b", s, re.IGNORECASE):
                m2 = re.search(r"\b(SS|GQQ|GQS|SQ|SQB)\s*(\d{1,2})\b", s, re.IGNORECASE)
                result["diameter"] = "DN" + m2.group(2)
        # 4c. 纯 DN 口径: DN150, DN100
        if not result.get("diameter"):
            m = re.search(r"DN\s*(\d+)(?!\d)", s, re.IGNORECASE)
            if m:
                result["diameter"] = "DN" + m.group(1)
        # 4d. DN口径范围: DN125~250
        if not result.get("diameter"):
            m = re.search(r"DN\s*(\d+)\s*~\s*(?:DN)?(\d+)", s, re.IGNORECASE)
            if m:
                result["diameter"] = "DN" + m.group(1) + "~" + m.group(2)
        # 4e. 阀体型号含 DN: DN150×100（多维度阀体，如三通）
        if not result.get("diameter"):
            m = re.search(r"DN\s*(\d+)\s*[×xX*]", s, re.IGNORECASE)
            if m:
                result["diameter"] = "DN" + m.group(1)
        # 4e. Φ 口径范围: Φ3~6, Φ10~12（先范围后单个，防止 Φ10 被单独截断）
        if not result.get("diameter"):
            m = re.search(r"(?<![A-Za-z])Φ\s*(\d+)\s*~\s*(\d+)", s)
            if m:
                result["diameter"] = "Φ" + m.group(1) + "~" + m.group(2)
        # 4f. 纯 Φ 口径: Φ50, Φ600
        # ── 自动生成: JDG管: JDGΦ25*1.6mm ──
        m = re.search(r'JDGΦ(\d+)\*(\d+(?:\.\d+)?)\s*mm', s)
        if m:
            result['diameter'] = 'Φ' + m.group(1)
            result['thickness'] = m.group(2) + 'mm'
        # ── 自动生成: 钢管 D*N*N: D720*8→{'diameter': 'D720', 'thickness': '8mm'} ──
        m = re.search(r'^D(\d+)\*(\d+)$', s)
        if m:
            result['diameter'] = 'D' + m.group(1)
            result['thickness'] = m.group(2) + 'mm'
        # ── 自动: test ──
        m = re.search(r'^D(\d+)\*(\d+)$', s)
        if m:
            result["diameter"] = "D"+m.group(1)
            result["thickness"] = m.group(2)+"mm"
        if not result.get("diameter"):
            m = re.search(r"(?<![A-Za-z])Φ\s*(\d+)", s)
            if m:
                result["diameter"] = "Φ" + m.group(1)
        # 4h. 等级标记 DN: DN15 A级, DN25 A级（DN 后面紧跟字母的）
        if not result.get("diameter"):
            m = re.search(r"DN\s*(\d+)\s+[A-Z]", s, re.IGNORECASE)
            if m:
                result["diameter"] = "DN" + m.group(1)

        # 5. 环刚度: SN8, SN10, SN12.5
        if not result.get("ring_stiffness"):
            m = re.search(r"\bSN(\d+(?:\.\d+)?)\b", s, re.IGNORECASE)
            if m:
                result["ring_stiffness"] = "SN" + m.group(1)

        # 6. 压力等级: PN1.6, PN1.0
        if not result.get("pressure"):
            m = re.search(r"\bPN(\d+(?:\.\d+)?)(?![\d.])", s, re.IGNORECASE)
            if m:
                result["pressure"] = "PN" + m.group(1)

        # 7. 材质
        # ── 自动生成: 水泥等级: 袋装P.S.A32.5 ──
        m = re.search(r'袋装\s*P\.S\.A\s*(\d+\.?\d*)', s)
        if m:
            result['grade'] = 'P.S.A' + m.group(1)
        material_kws = {
            "PE": "PE", "PVC": "PVC", "PPR": "PPR", "PP": "PP", "PB": "PB",
            "铸铁": "铸铁", "钢": "钢", "不锈钢": "不锈钢", "铜": "铜",
            "铝合金": "铝合金", "PEX": "PEX", "CPVC": "CPVC",
        }
        if not result.get("material"):
            for kw, val in material_kws.items():
                if kw in s:
                    result["material"] = val
                    break
        if not result.get("material"):
            surface_kws = {
                "内外热镀锌": "内外热镀锌", "热镀锌": "热镀锌", "冷镀锌": "冷镀锌",
                "喷塑": "喷塑", "烤漆": "烤漆", "浸塑": "浸塑",
                "衬塑": "衬塑", "涂塑": "涂塑", "环氧": "环氧",
                "聚乙烯": "聚乙烯", "聚氯乙烯": "聚氯乙烯",
            }
            for kw, val in surface_kws.items():
                if kw in s:
                    result["material"] = val
                    break
        if not result.get("series"):
            m = re.search(r"\b(\d+)\s*系列\b", s)
            if m:
                result["series"] = m.group(1) + "系列"

        # 8. 颜色
        if not result.get("color"):
            color_kws = ["白", "黑", "红", "蓝", "绿", "黄", "灰", "米色", "银", "金", "透明"]
            for kw in color_kws:
                if kw in s:
                    result["color"] = kw
                    break

        # 9. 牌号/等级/钢牌号
        grade_patterns = [
            (r"P\.O42\.5R?", "grade"), (r"P\.O52\.5R?", "grade"),
            (r"P\.II42\.5", "grade"), (r"P\.II52\.5", "grade"),
            (r"(?<![a-zA-Z0-9])C(\d+)(?![a-zA-Z0-9])", "grade"),
            (r"(SBS)?AC-?(\d+)", "asphalt_type"), (r"水泥含量(\d+)%", "cement_content"),
            (r"\b(D?Q235|Q345|HRB335|HRB400|HPB300)\b", "grade"),
            (r"(?<![a-zA-Z])Q\d{3}[A-Z]\b", "grade"),
            (r"甲级|乙级|丙级|丁级", "fire_rating"),
        ]
        for pat, field in grade_patterns:
            if field not in result:
                m = re.search(pat, s, re.IGNORECASE)
                if m:
                    result[field] = m.group(0).upper() if field in ("grade", "asphalt_type") else m.group(0)

        # H型钢高度范围
        if "height_range" not in result:
            m = re.search(r"H(\d+)\s*~\s*(?:H)?(\d+)", s, re.IGNORECASE)
            if m:
                result["height_range"] = f"H{m.group(1)}~H{m.group(2)}"

        # 10. 电压等级 / IP防护等级
        if not result.get("voltage"):
            m = re.search(r"(\d+)\s*[VVA](?:\d+)?\s*[A]?\s*A\b", s)
            if not m:
                m = re.search(r"(\d+)\s*[VVA]", s)
            if m:
                val = m.group(1)
                if int(val) >= 220:
                    result["voltage"] = val
        # IP防护等级: IP54, IP65, IP67
        if not result.get("ip_rating"):
            m = re.search(r"\bIP(\d+)\b", s, re.IGNORECASE)
            if m:
                result["ip_rating"] = "IP" + m.group(1)

        # 11. 电流
        if not result.get("current"):
            m = re.search(r"\b(\d+)\s*A\b", s)
            if m:
                result["current"] = m.group(1)

        # 12. 设备规格
        channels_kws = ["8路", "4路", "2路", "1路", "多路", "N路"]
        for kw in channels_kws:
            if kw in s and not result.get("channels"):
                result["channels"] = kw
        doors_kws = ["2门", "4门", "多门", "单门"]
        for kw in doors_kws:
            if kw in s and not result.get("doors"):
                result["doors"] = kw

        # 13. 光纤规格
        if not result.get("fiber_core"):
            m = re.search(r"芯直径[:：]\s*(\d+/\d+)\s*μm", s)
            if m:
                result["fiber_core"] = m.group(1) + "μm"

        # 14. 跳线/线缆长度（要求空格 + m，避免匹配 H=0.36m）
        if not result.get("length_range"):
            m = re.search(r"(\d+)\s*[～~]\s*(\d+)\s+m", s)
            if m:
                result["length_range"] = m.group(1) + "m~" + m.group(2) + "m"
        if not result.get("length_range"):
            m = re.search(r"长度\s*[:：]\s*(\d+(?:\.\d+)?)\s+cm", s)
            if m:
                result["length_range"] = m.group(1) + "cm"
        if not result.get("length_range"):
            m = re.search(r"\b(\d+(?:\.\d+)?)\s+m\b", s)
            if m:
                result["length_range"] = m.group(1) + "m"
        if not result.get("length_range"):
            m = re.search(r"\b(\d+(?:\.\d+)?)\s+cm\b", s)
            if m:
                result["length_range"] = m.group(1) + "cm"

        # 14b. 长度前缀: 长度1500（无单位，默认mm）
        if not result.get("length"):
            m = re.search(r"长度(\d+)", s)
            if m:
                result["length"] = m.group(1) + "mm"

        # 14c. 内径+壁厚: 内径260*230 壁厚80 → inner_diameter + wall_thickness
        if not result.get("inner_diameter"):
            m = re.search(r"内径\s*(\d+)\s*[×xX*]\s*(\d+)\s*壁厚\s*(\d+)", s)
            if m:
                result["inner_diameter"] = m.group(1) + "mm"
                result["wall_thickness"] = m.group(3) + "mm"
            else:
                m = re.search(r"内径\s*(\d+)\s*[×xX*]\s*(\d+)", s)
                if m:
                    result["inner_diameter"] = m.group(1) + "mm"

        # 14d. 机柜规格: 42U, 宽600*深600*高2050
        if not result.get("height"):
            m = re.search(r"(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+)\s*高", s)
            if m:
                result["length"] = m.group(1) + "mm"
                result["width"] = m.group(2) + "mm"
                result["height"] = m.group(3) + "mm"
            else:
                m = re.search(r"宽\s*(\d+)\s*[×xX*]\s*深\s*(\d+)\s*[×xX*]\s*高\s*(\d+)", s)
                if m:
                    result["length"] = m.group(1) + "mm"
                    result["width"] = m.group(2) + "mm"
                    result["height"] = m.group(3) + "mm"
        if not result.get("series"):
            m = re.search(r"(\d+)\s*U", s)
            if m:
                result["series"] = m.group(1) + "U"

        # 14e. 钢材角度规格: ∠30×20mm~63×40mm Q235B → L×W + grade
        if not result.get("length"):
            m = re.search(r"∠(\d+)\s*[×xX*]\s*(\d+)\s*mm", s)
            if m:
                result["length"] = m.group(1) + "mm"
                result["width"] = m.group(2) + "mm"

        # 14f. 温度+尺寸复合型: 70℃800*800, 70℃ 800×800（温度在前，尺寸在后）
        if not result.get("temperature") and not result.get("length"):
            m = re.search(r"(\d+)\s*℃\s*(\d+)\s*[×xX*]\s*(\d+)", s)
            if m:
                result["temperature"] = m.group(1) + "℃"
                result["length"] = m.group(2) + "mm"
                result["width"] = m.group(3) + "mm"
            else:
                m = re.search(r"(\d+)\s*℃\s*(\d+)", s)
                if m:
                    result["temperature"] = m.group(1) + "℃"
                    remaining = s[s.index(m.group(0)) + len(m.group(0)):].strip()
                    m2 = re.search(r"(\d+)\s*[×xX*]\s*(\d+)", remaining)
                    if m2:
                        result["length"] = m2.group(1) + "mm"
                        result["width"] = m2.group(2) + "mm"

        # 15. 液位变送器规格
        if "液位变送器" in s or "液位仪" in s:
            if not result.get("media"):
                m = re.search(r"介质[:：]\s*(\S+)", s)
                if m:
                    result["media"] = m.group(1)
            if not result.get("range"):
                m = re.search(r"量程[:：]\s*(\S+)", s)
                if m:
                    result["range"] = m.group(1)
            if not result.get("cable_length"):
                m = re.search(r"电缆长度\s*[L=]\s*(\d+(?:\.\d+)?)\s+m", s)
                if m:
                    result["cable_length"] = "L=" + m.group(1) + "m"
            if not result.get("output"):
                m = re.search(r"输出[:：]\s*(\S+)", s)
                if m:
                    result["output"] = m.group(1)

        # 16. 温湿度范围
        if not result.get("temp_range"):
            m = re.search(r"温度[:：]\s*([-\d]+)\s*[℃]\s*[～~]\s*([-\d]+)\s*[℃]", s)
            if m:
                result["temp_range"] = m.group(1) + "℃~" + m.group(2) + "℃"
        if not result.get("temperature"):
            m = re.search(r"温度[:：]\s*([-\d]+)\s*℃", s)
            if m:
                result["temperature"] = m.group(1) + "℃"
        if not result.get("humidity_range"):
            m = re.search(r"湿度[:：]\s*(\d+)\s*~(\d+)\s*%RH", s)
            if m:
                result["humidity_range"] = m.group(1) + "%~" + m.group(2) + "%RH"

        # ========== H=0.36m 等小数高度（在 step14 之后，防止被 length_range 误捕）==========
        if not result.get("height"):
            m = re.search(r"H\s*=\s*([\d.]+)\s*m", s, re.IGNORECASE)
            if m:
                val = m.group(1)
                if "." in val:
                    result["height"] = str(int(float(val) * 1000)) + "mm"
                else:
                    result["height"] = val + "mm"

        # 14g. δ厚度范围+材质: δ0.5~2SS304, δ2.5~5 SS304（先于 step17 的 δ 单值 fallback）
        if not result.get("thickness"):
            # δ0.5~2SS304 或 δ0.5~2 SS304：范围+材质
            m = re.search(r"δ(\d+\.?\d*)\s*~\s*(\d+\.?\d*)\s*([A-Za-z0-9]+)\s*$", s)
            if m:
                result["thickness"] = "δ" + m.group(1) + "~" + m.group(2)
                mat = m.group(3)
                if mat.upper() in ("SS304", "SS316", "SS321", "SS316L", "SS304L"):
                    result["material"] = "不锈钢"
                    result["grade"] = mat.upper()
                elif "SS" in mat.upper():
                    result["material"] = "不锈钢"
            else:
                # δ0.5~2（无材质后缀）
                m = re.search(r"δ(\d+\.?\d*)\s*~\s*(\d+\.?\d*)\s*$", s)
                if m:
                    result["thickness"] = "δ" + m.group(1) + "~" + m.group(2)

        # ========== 城市特有规则（子类覆盖）==========
        result = self._city_rules(s, result)

        # ========== 通用 fallback 规则 ==========        # 17. δ 厚度标记（存原始格式，如 δ0.4，不加 mm 后缀）
        if not result.get("thickness"):
            m = re.search(r"δ(\d+\.?\d*)\s*$", s)
            if m:
                result["thickness"] = "δ" + m.group(1)
            else:
                m = re.search(r"δ\s*=\s*(\d+\.?\d*)", s)
                if m:
                    result["thickness"] = "δ=" + m.group(1)

        # 17b. φ 直径标记（存原始格式，如 φ50）
        if not result.get("diameter"):
            m = re.search(r"φ(\d+)\s*$", s)
            if m:
                result["diameter"] = "Φ" + m.group(1)
            else:
                m = re.search(r"Φ(\d+)\s*$", s)
                if m:
                    result["diameter"] = "Φ" + m.group(1)

        # 17b. 铸铁/钢制散热器高度: 四柱760型H=600, 双柱H=600
        if not result.get("height"):
            m = re.search(r"(双|四|单)柱\s*(\d+型)?\s*H\s*=\s*(\d+)", s)
            if m:
                if m.group(2):
                    result["form"] = m.group(1) + "柱" + m.group(2)
                else:
                    result["form"] = m.group(1) + "柱"
                result["height"] = m.group(3) + "mm"
        # 17d. 多叶风口 W*(H1+H2)
        if not result.get("width"):
            m = re.search(r"^(\d{3,4})\s*\*\s*\((\d+)\s*\+\s*(\d+)", s)
            if m:
                result["width"] = m.group(1) + "mm"
                result["height"] = str(int(m.group(2)) + int(m.group(3))) + "mm"

        # 17e. 温度+外形尺寸复合型
        if not result.get("temperature"):
            m = re.search(r"(\d+)\s*℃\s*外形尺寸[≤≤≤]\s*(\d+)\s*[×xX*]\s*(\d+)", s)
            if m:
                result["temperature"] = m.group(1) + "℃"
                result["length"] = m.group(2) + "mm"
                result["width"] = m.group(3) + "mm"

        # 18. 纯厚度 fallback
        if not result.get("length") and not result.get("thickness"):
            m = re.search(r"^(\d+\.?\d*)\s*(?:mm)?$", s)
            if m:
                result["thickness"] = m.group(1) + "mm"

        # 18e. 面板/开关插座 规格类型: 86型, 118型, 120型
        if not result.get("form"):
            for kw in ["86型", "118型", "120型", "146型"]:
                if kw in s:
                    result["form"] = kw
                    break

        # 18f. 安装类型（台下盆等）
        if not result.get("installation_type"):
            for kw in ["台下盆", "台上盆", "立柱盆", "壁挂式", "挂墙式", "半嵌盆"]:
                if kw in s:
                    result["installation_type"] = kw
                    break

        # 18g. 排水类型
        if not result.get("drain_type"):
            for kw in ["下出水", "后进水地排水", "地排水", "侧排水", "后进后出", "后进前出"]:
                if kw in s and s != kw:
                    result["drain_type"] = kw
                    break
            else:
                # 精确匹配时：仅写入 drain_type，不写 inlet_type
                if s in ["下出水", "后进水地排水", "地排水", "侧排水", "后进后出", "后进前出"]:
                    result["drain_type"] = s

        # 18h. 进水类型（排除已在 drain_type 处理过的精确匹配）
        if not result.get("inlet_type"):
            for kw in ["后进水", "侧进水", "上进水"]:
                if kw in s and s != kw:
                    result["inlet_type"] = kw
                    break
            # 精确匹配：后进后出/后进前出 不写入 inlet_type（由 drain_type 承载）
            if s in ["后进后出", "后进前出"]:
                pass

        # 19. 无单位尺寸 AxB
        if not result.get("length") and not result.get("thickness"):
            m = re.search(r"^(\d{3,4})\s*[×xX*]\s*(\d{3,4})(?:\s|$)", s)
            if m:
                result["length"] = m.group(1) + "mm"
                result["width"] = m.group(2) + "mm"

        # 19b. 钢格栅/钢格盖板编号: G755/40/100
        if not result.get("grade"):
            m = re.search(r"\bG\d{3}/\d+/\d+\b", s)
            if m:
                result["grade"] = m.group(0)

        # 19c. 门型号: M2蜂窝板门, M1022
        if not result.get("grade"):
            m = re.search(r"\bM\d+\S*", s)
            if m:
                result["grade"] = m.group(0)

        # 19d. 防水卷材类: CPS-TS 1.5mm YT类（复合结构）
        if not result.get("series"):
            m = re.search(r"^([A-Za-z0-9\-]+)\s*(\d+(?:\.\d+)?)\s*mm\s*([^（\s]+类)", s)
            if m:
                result["series"] = m.group(1)
                result["thickness"] = m.group(2) + "mm"
                result["form"] = m.group(3)
                # 括号内复合结构描述写入 grade
                m2 = re.search(r"（(.+?)）", s)
                if m2:
                    result["grade"] = m2.group(1)

        return result

    def _city_rules(self, s: str, result: dict) -> dict:
        """城市特有规则，子类覆盖"""
        return result


def clean_spec(spec: str) -> str:
    """清理规格字符串"""
    if not spec or spec == "/" or spec == "":
        return "/"
    s = spec.strip().replace("\u00d7", "*")
    s = re.sub(r"\s+", " ", s).strip()
    return s