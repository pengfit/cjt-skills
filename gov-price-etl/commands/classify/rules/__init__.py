# classify/rules/__init__.py
"""
classify/rules/ - 品种分类规则目录（仿 parse_spec/rules 结构）

规则文件：
  _core.py      - 核心分类函数 classify_breed()
  breed.py      - 品种片段→分类（BREED_CAT_MAP）
  keyword.py    - 关键词→分类（KEYWORD_RULES）
  species.py    - 短品种规格辅助推断（SPEC_HINT_RULES）

维护方式：
  通过 Dashboard UI 的规则确认按钮追加写入 rules/
  禁止在 _core.py 中硬编码规则
"""
import os, re

RULES_DIR = os.path.dirname(__file__)
CLASSIFICATIONS = [
        # 土建
        "钢材",
        "水泥",
        "砂石骨料",
        "石材",
        "砖/砌块",
        "瓦",
        "木材",

        # 金属
        "金属材料",
        "铜材",
        "铝材/铝合金",
        "不锈钢材料",
        "铁艺/铸铁件",

        # 安装工程
        "管材管件",
        "阀门",
        "泵类设备",
        "暖通空调设备",
        "消防器材",
        "电气材料",
        "电线电缆",
        "照明设备",
        "配电设备",
        "弱电智能化",

        # 装饰装修
        "装饰装修材料",
        "涂料/油漆",
        "陶瓷/卫生洁具",
        "龙骨/吊顶",
        "门窗幕墙",

        # 功能材料
        "防水材料",
        "保温材料",
        "密封材料",
        "化工材料",
        "土工材料",

        # 市政园林
        "市政设施",
        "绿化苗木",

        # 五金
        "五金配件",

        # 设备机械
        "机械设备",
        "施工机械",

        # 服务
        "公用事业费",
        "劳务/工种"]


# 规则格式: "关键词" → "分类"
_RULE_RE = re.compile(r'^"([^"]+)"\s*→\s*"([^"]+)"', re.MULTILINE)


def get_rules():
    """动态加载 rules/ 目录下所有规则"""
    rules = []
    for py_file in sorted(os.listdir(RULES_DIR)):
        if py_file.startswith('_') or py_file == '__init__.py' or not py_file.endswith('.py'):
            continue
        with open(os.path.join(RULES_DIR, py_file)) as f:
            content = f.read()
        for m in _RULE_RE.finditer(content):
            rules.append({
                "keyword": m.group(1),
                "category": m.group(2),
                "file": py_file,
            })
    return rules


__all__ = ["CLASSIFICATIONS", "get_rules", "get_categories", "RULES_DIR"]


def get_categories():
    """从 rules/ 动态获取所有已注册的分类（去重）"""
    cats = set(rule["category"] for rule in get_rules())
    return sorted(cats)