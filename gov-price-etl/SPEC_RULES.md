# parse_spec 规格规则库使用说明

## 一、架构概览

```
parse_spec/
├── __init__.py      # get_parser() 入口
├── base.py          # 槽位制解析基类（RAG 召回 + 独立竞争）
├── rules/
│   ├── vector_store.py   # 规则向量库（SQLite，唯一数据源）
│   ├── rules_vec.db      # 规则存储（SQLite）
│   └── _attrs.py          # 属性槽位定义（ATTR_SLOTS）
└── __init__.py
```

**规则唯一来源：`rules_vec.db`**（SQLite），不再从 rules/*.py 解析。

解析流程：
1. 对每个 `ATTR_SLOTS` 槽位（如 `length`、`width`、`height`），独立调用 `vector_store.search()` 召回候选规则
2. 候选规则与 spec 字符串做 Jaccard 相似度过滤（score ≥ 0.001）
3. 按 score 排序，去重（同 attr + pattern 保留最高分），取 top_k
4. 逐条执行 regex match + code，填入对应 slot
5. 全部未命中 → 调用 fix-case API

---

## 二、规则表结构（rules_vec.db）

```sql
CREATE TABLE rule_vectors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT    NOT NULL,
    attr        TEXT    NOT NULL,
    note        TEXT    DEFAULT '',
    code        TEXT    DEFAULT '',
    breed       TEXT    DEFAULT '',
    category    TEXT    DEFAULT '',
    tokens      TEXT    DEFAULT '[]',   -- JSON list，结构语义标签
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(pattern, attr, breed, category)
)
```

| 字段 | 说明 | 示例 |
|------|------|------|
| `id` | 自增主键 | 1, 2, 3... |
| `pattern` | 正则表达式（**不含** r 前缀） | `^(\d+)×\d+×\d+$` |
| `attr` | 解析目标属性 | `length`, `width`, `height` |
| `note` | 规则说明 | `三段式 L×W×H` |
| `code` | 执行代码（可选） | `m = re.search(...)` |
| `breed` | 适用品种（空=通用） | `砖渣多孔砖` |
| `category` | 适用分类（空=通用） | `瓦` |
| `tokens` | **结构语义标签**（JSON list） | `["三段","LWW","长宽高","尺寸"]` |
| `created_at` | 写入时间 | `2026-05-27 08:45:00` |

---

## 三、Tokens 生成机制

tokens 是**结构语义标签**，不是 metadata 或正则字符串本身。

### `_build_tokens(pattern, attr, breed, category)` — 规则写入时自动生成

从 pattern 结构特征检测：

| 检测条件 | 添加标签 |
|----------|---------|
| 包含捕获组 `()` | `数字捕获`, `数字` |
| 包含 `[dwspn]` 转义序列 | `精确匹配`, `格式`, `转义字符` |
| 包含 `[` 字符类 | `字符类`, `非数字` |
| 维度分隔符 `×` ≥ 2 个 | `三段`, `LWW`, `长宽高`, `尺寸` |
| 维度分隔符 `×` = 1 个 | `两段`, `两尺寸`, `尺寸` |
| 包含小数点 `.` | `小数`, `浮点`, `尺寸`, `数字` |
| `^...$` 精确边界 | `精确匹配`, `格式` |
| breed 参数 | `breed` 值（如 `砖渣多孔砖`） |
| category 参数 | `category` 值（如 `瓦`） |
| attr 参数 | `attr` 值（如 `length`） |

示例：
```
pattern = "^(\d+)×\d+×\d+$", attr = "length", breed = "砖渣多孔砖", category = "瓦"
→ tokens = ["数字捕获", "数字", "三段", "LWW", "长宽高", "尺寸", "砖渣多孔砖", "瓦", "length"]
```

### `_build_spec_tokens(spec)` — 搜索时对 spec 字符串生成

从 spec 字符串结构检测：

| 检测条件 | 添加标签 |
|----------|---------|
| `×` 分隔符 ≥ 2 个（如 `240×115×90`） | `三段`, `LWW`, `长宽高`, `尺寸`, `数字` |
| `×` 分隔符 = 1 个 | `两段`, `两尺寸`, `尺寸`, `数字` |
| 包含小数点 | `小数`, `浮点`, `数字` |
| 纯数字格式（无中文无字母） | `数字` |

示例：
```
spec = "240×180×90"  →  tokens = {"三段", "LWW", "长宽高", "尺寸", "数字"}
spec = "600×240×80~120mm"  →  {"三段", "LWW", "长宽高", "尺寸", "数字"}
spec = "360×220mm"   →  {"两段", "两尺寸", "尺寸", "数字"}
```

### Jaccard 相似度

```
score = |spec_tokens ∩ rule_tokens| / |spec_tokens ∪ rule_tokens|
```

- score ≥ 0.001 才参与竞争，否则直接丢弃
- 无命中 → 返回空列表（**不降级，不复用旧规则**）

---

## 四、如何添加规则

### 方式一：API 界面（推荐）

**1. 访问规则管理页面**
```
GET http://localhost:5200/api/stats/rules-vector?page=1&page_size=50
```
查看现有规则，支持按 `attr`、`category`、`search` 过滤。

**2. fix-case 接口（解析失败的 spec 自动生成规则）**
```
POST http://localhost:5200/api/stats/spec-quality/fix-case
Body: {
  "city": "xian",
  "spec": "240×180×90",
  "breed": "砖渣多孔砖",
  "category": "瓦",
  "expected": {"length": "240", "width": "180", "height": "90"},
  "confirm": true
}
```
confirm=true 时写入 `rules_vec.db`（同时更新 rules/*.py 作为备份）。

**3. refresh-category 接口（批量清洗）**
```
POST http://localhost:5200/api/stats/spec-quality/refresh-category
Body: {"city": "xian", "category": "瓦"}
```

### 方式二：直接插入（Python 脚本）

```python
import sys, json
sys.path.insert(0, "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl/commands")
import importlib, parse_spec.rules.vector_store as vs_mod
importlib.reload(vs_mod)
vs_mod._store = None  # 强制重新初始化

vs = vs_mod.get_vec_store()

# 插入规则（tokens 自动生成，无需手动指定）
vs.insert(
    pattern=r'^(\d+)×\d+×\d+$',
    attr='length',
    note='三段式 L×W×H，第一组为 length',
    breed='砖渣多孔砖',
    category='瓦'
)
vs.insert(pattern=r'^\d+×(\d+)×\d+$', attr='width',  breed='砖渣多孔砖', category='瓦')
vs.insert(pattern=r'^\d+×\d+×(\d+)$', attr='height', breed='砖渣多孔砖', category='瓦')

# 验证
conn = vs_mod.sqlite3.connect(vs.db_path)
rows = conn.execute("SELECT id, pattern, attr, breed, tokens FROM rule_vectors").fetchall()
for r in rows:
    print(f"id={r[0]} attr={r[2]:12} pattern={r[1]} tokens={json.loads(r[4])}")
conn.close()
```

### 方式三：SQL 直接写入（不推荐）

```bash
sqlite3 commands/parse_spec/rules/rules_vec.db "
INSERT INTO rule_vectors (pattern, attr, note, breed, category, tokens)
VALUES (
  '^(\d+)×\d+×\d+$',
  'length',
  '三段式 L×W×H',
  '砖渣多孔砖',
  '瓦',
  '[\"三段\",\"LWW\",\"长宽高\",\"尺寸\",\"数字\",\"砖渣多孔砖\",\"瓦\",\"length\"]'
);
"
```
⚠️ 手动指定 tokens 容易出错，建议用方式二（自动生成）。

---

## 五、添加规则检查清单

新增规则前，确认以下全部满足：

1. **pattern 格式**：不含 `r""` 前缀，直接写正则字符串（如 `^(\d+)×\d+×\d+$`）
2. **捕获组对应 attr**：
   - `length` = 第 1 个 `()` 捕获的内容
   - `width` = 第 2 个 `()` 捕获的内容
   - `height` = 第 3 个 `()` 捕获的内容
3. **breed + category 精确**：如果规则只适用于特定品种，填入对应字段
4. **无重复规则**：同 (pattern, attr, breed, category) 已存在会 UNIQUE 约束失败
5. **验证 parse 结果**：插入后用 `parser.parse(spec, breed, category)` 测试

---

## 六、测试验证

```bash
cd /Users/pengfit/.openclaw/workspace/skills/gov-price-etl

# 测试 spec 解析
python3 -c "
import sys; sys.path.insert(0, 'commands')
from parse_spec import get_parser
parser = get_parser('xian')

test_cases = [
    ('240×180×90', '砖渣多孔砖', '瓦'),
    ('600×240×80~120mm', '加气砼砌块', '瓦'),
    ('190×90×190', '轻集料块', '瓦'),
    ('360×220mm', '粘土红平瓦', '瓦'),
    ('300×900×18mm', '红色陶板', '瓦'),
]
for spec, breed, cat in test_cases:
    result = parser.parse(spec, breed, cat)
    ok = '✓' if result.get('length') or result.get('height_range') else '✗'
    print(f'{ok} spec={spec!r:30} → {result}')
"

# 测试向量库召回
python3 -c "
import sys; sys.path.insert(0, 'commands')
from parse_spec.rules.vector_store import get_vec_store, _build_spec_tokens
vs = get_vec_store()

spec = '240×180×90'
tokens = _build_spec_tokens(spec)
print(f'spec_tokens: {tokens}')

results = vs.search(spec=spec, category='瓦', breed='砖渣多孔砖', top_k=10)
print(f'search hits: {len(results)}')
for score, r in results:
    print(f'  score={score:.4f} attr={r[\"attr\"]:12} pattern={r[\"pattern\"]!r}')
"
```

---

## 七、常见问题

**Q: 规则插入报 UNIQUE constraint failed**
A: 同 (pattern, attr, breed, category) 已存在。先查 `SELECT * FROM rule_vectors WHERE pattern=?`，确认是否重复。

**Q: parse 结果为空，但规则存在**
A: 检查 spec_tokens 和 rule_tokens 是否有交集：
```python
from parse_spec.rules.vector_store import _build_spec_tokens, _keyword_score
spec_tokens = _build_spec_tokens('240×180×90')
rule_tokens = frozenset(['三段','LWW','长宽高','尺寸'])
score = _keyword_score(spec_tokens, rule_tokens)
print(f'score={score}')  # 必须 ≥ 0.001
```

**Q: refresh-category 后 needs_spec_parse 没有变化**
A: 确认 transform_doc 的 parser 实例使用了最新的 vector_store（单例，重启进程后生效）。

---

## 八、SQL 常用查询

```bash
cd /Users/pengfit/.openclaw/workspace/skills/gov-price-etl

# 查看所有规则
sqlite3 commands/parse_spec/rules/rules_vec.db "SELECT id, attr, breed, category, pattern FROM rule_vectors"

# 按 attr 统计
sqlite3 commands/parse_spec/rules/rules_vec.db "SELECT attr, COUNT(*) FROM rule_vectors GROUP BY attr"

# 按 breed 统计
sqlite3 commands/parse_spec/rules/rules_vec.db "SELECT breed, COUNT(*) FROM rule_vectors GROUP BY breed"

# 删除重复规则（保留 id 最小）
sqlite3 commands/parse_spec/rules/rules_vec.db "
DELETE FROM rule_vectors WHERE id NOT IN (
  SELECT MIN(id) FROM rule_vectors
  GROUP BY pattern, attr, breed, category
)
"

# 清空所有规则
sqlite3 commands/parse_spec/rules/rules_vec.db "DELETE FROM rule_vectors"
```