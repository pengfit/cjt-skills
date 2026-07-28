<template>
  <div class="ctx-page">
    <!-- PageHeader (matching /taxonomy flat variant) -->
    <PageHeader
      variant="flat"
      title="规格规则库"
      subtitle="存储在 <code>breed_spec_rules.db</code>（SQLite + Blob），ETL DWD→DWS 阶段 3 AI 自动回写；本页支持 <code>pattern+attr+code</code> 多维检索"
      :stats="[
        { label: '规则总数', value: fmt.int(vecRules.total) },
        { label: '当前页', value: `${vecRules.page} / ${vecRules.pages || 1}` },
      ]"
    />

    <!-- 3-column stat cards (Top attrs / Top L3 / Query context) — 借鉴 /taxonomy 的 .ctx-conf-cards -->
    <!-- 激活筛选 chips (横条) — 借鉴 /taxonomy 的 source tag 样式 -->
    <Transition name="slide-down">
      <div class="vec-chips" v-if="activeChips.length">
        <span class="vec-chips-label">当前筛选</span>
        <span
          v-for="chip in activeChips" :key="chip.key"
          class="vec-chip" @click="clearOne(chip)"
          :title="`移除 ${chip.label}`"
        >{{ chip.label }}<span class="vec-chip-x">×</span></span>
        <button class="vec-chips-clear-all" @click="clearAllFilters" title="一键清除所有筛选">全部清除</button>
      </div>
    </Transition>

    <!-- Toolbar -->
    <div class="vec-toolbar">
      <div class="vec-toolbar-main">
        <input class="vec-input" v-model="vecSearch" placeholder="🔍 搜索 pattern / note / code..." @input="loadVecRules(1)" />
        <button v-if="vecSearch" class="vec-clear-btn" @click="vecSearch = ''; loadVecRules(1)" title="清除搜索">×</button>
      </div>
      <div class="vec-toolbar-side">
        <button class="vec-help-btn" :class="{ active: showHelp }" @click="showHelp = !showHelp">
          {{ showHelp ? '🔼 收起说明' : '📖 使用说明' }}
        </button>
      </div>
    </div>

    <!-- 帮助区 (collapsible) -->
    <Transition name="slide-down">
      <div class="vec-help" v-if="showHelp">
        <div class="vec-help-grid">
          <div class="vec-help-row"><b>是什么</b>存储于 <code>breed_spec_rules.db</code> 的解析正则 + Python 代码，由 sync_dws stage 3 自动回写。</div>
          <div class="vec-help-row"><b>怎么检索</b>关键字（pattern / note / code）+ 日期范围 组合查询。</div>
          <div class="vec-help-row"><b>怎么新增</b>暂无人工入口，自动从 AI 解析成功后回写；脏数据可通过 <code>DELETE FROM breed_spec_rules</code> 清理。</div>
          <div class="vec-help-row"><b>字段含义</b><code>attr</code> 业务属性名；<code>pattern</code> 不带 <code>r</code> 前缀的 regex；<code>code</code> 单行或 <code>\\n</code> 多行 Python；<code>l3</code> 召回 +0.40 加权。</div>
        </div>
      </div>
    </Transition>

    <!-- 2026-07-28:Phase 2 — 自研 CSS Grid 改 Element Plus <el-table> -->
    <div class="vec-table-wrap">
      <el-table
        v-loading="vecLoading"
        :data="vecRules.items || []"
        stripe
        class="vec-el-table"
        empty-text="暂无规则"
        :row-key="(r) => r.id"
      >
        <el-table-column type="index" :index="(i) => (vecRules.page - 1) * vecPageSize + i + 1" label="#" width="60" align="center" />
        <el-table-column prop="breed" label="breed" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span :title="row.breed">{{ row.breed || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="attr" label="属性" width="120" align="center">
          <template #default="{ row }">
            <span class="vec-attr-tag">{{ row.attr || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="l3" label="L3 分项" width="120" align="center">
          <template #default="{ row }">{{ row.l3 || '—' }}</template>
        </el-table-column>
        <el-table-column prop="pattern" label="pattern" min-width="180">
          <template #default="{ row }">
            <code class="vec-pattern" :title="row.pattern">{{ row.pattern }}</code>
          </template>
        </el-table-column>
        <el-table-column label="code" min-width="220">
          <template #default="{ row }">
            <pre class="vec-code-block" v-html="highlightPy(row.code || '')"></pre>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="note" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.note || '—' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ row.created_at ? row.created_at.slice(0, 19) : '—' }}
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 分页 -->
    <div class="vec-pagination" v-if="vecRules.pages > 1">
      <button class="page-btn nav" :disabled="vecRules.page <= 1" @click="loadVecRules(vecRules.page - 1)">‹</button>
      <button
        v-for="p in vecPageRange" :key="p" class="page-btn"
        :class="{ active: Number(p) === Number(vecRules.page), ellipsis: p === '...' }"
        :disabled="p === '...'"
        @click="p !== '...' && loadVecRules(Number(p))"
      >{{ p }}</button>
      <button class="page-btn nav" :disabled="vecRules.page >= vecRules.pages" @click="loadVecRules(vecRules.page + 1)">›</button>
      <div class="page-jump-wrap">
        <span>跳至</span>
        <input class="page-jump" v-model.number="vecJumpPage" @keyup.enter="goToVecPage" type="number" min="1" :max="vecRules.pages" />
        <span>页</span>
      </div>
      <div class="page-size-wrap">
        <span>每页</span>
        <select class="page-size-select" v-model.number="vecPageSize" @change="loadVecRules(1)">
          <option v-for="s in vecPageSizeOptions" :key="s" :value="s">{{ s }}</option>
        </select>
        <span>条</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'

import PageHeader from './PageHeader.vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'

const API = import.meta.env.VITE_API_URL || '/api'
const fmt = useFormatNumber()

// ── 表格 CSS Grid 列模板 (fr 比例，等宽分布) ──
const GRID_COLS = '52px minmax(110px, 1.4fr) minmax(90px, 1fr) minmax(110px, 1.1fr) minmax(150px, 1.6fr) minmax(260px, 2.4fr) minmax(120px, 1fr) minmax(150px, 1fr)'

// ── 响应式状态 ──
const vecRules = ref({ total: 0, page: 1, pages: 1, items: [], attr_options: [], category_options: [], l3_options: [] })
const vecPageSize = ref(50)
const vecPageSizeOptions = [50, 100, 200]
const vecJumpPage = ref(1)

const vecSearch = ref('')
const vecOrder = ref('desc')
const vecLoading = ref(false)
const showHelp = ref(false)

// ── 衍生统计 ──
const vecPageRange = computed(() => {
  const tp = vecRules.value.pages
  const cur = vecRules.value.page
  if (!tp) return []
  if (tp <= 7) return Array.from({ length: tp }, (_, i) => i + 1)
  const set = new Set([1, tp, cur, cur - 1, cur + 1])
  const list = [...set].filter(n => n >= 1 && n <= tp).sort((a, b) => a - b)
  const out = []
  for (let i = 0; i < list.length; i++) {
    if (i > 0 && list[i] - list[i - 1] > 1) out.push('...')
    out.push(list[i])
  }
  return out
})

// 激活筛选条件汇总（用于顶部 chips 横条 + 卡片展示）
const activeChips = computed(() => {
  const cs = []
  if (vecSearch.value) cs.push({ key: 'search', label: '🔍 「' + vecSearch.value + '」', clear: () => { vecSearch.value = '' } })
  return cs
})

// ── 交互 ──
function clearOne(chip) {
  chip.clear()
  loadVecRules(1)
}

function clearAllFilters() {
  vecSearch.value = ''
  loadVecRules(1)
}

function toggleOrder() {
  vecOrder.value = vecOrder.value === 'desc' ? 'asc' : 'desc'
  loadVecRules(1)
}

function goToVecPage() {
  const p = Number(vecJumpPage.value)
  if (p >= 1 && p <= vecRules.value.pages && p !== vecRules.value.page) {
    loadVecRules(p)
  }
}

// ── 网络 ──
async function loadVecRules(page = 1) {
  vecLoading.value = true
  try {
    const params = { page, page_size: vecPageSize.value, order: vecOrder.value }
    if (vecSearch.value) params.search = vecSearch.value
    const res = await axios.get(`${API}/stats/rules-vector`, { params })
    vecRules.value = res.data || {}
    } catch (e) {
    console.warn('rules-vector failed', e)
  } finally {
    vecLoading.value = false
  }
}

// ── URL query 同步 (search 直达链接) ──
const route = useRoute()
const router = useRouter()
if (route.query.search) vecSearch.value = String(route.query.search)

watch([vecSearch], () => {
  const q = { ...route.query }
  if (vecSearch.value) q.search = vecSearch.value
  else delete q.search
  router.replace({ query: q })
})

// ── Python 代码染色 (高亮注释/字符串/关键字/数字) ──
function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
function highlightPy(code) {
  if (!code) return ''
  return code
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/(#[^\n]*)/g, '<span class="cm-comment">$1</span>')
    .replace(/(\'[^\n]*\'|"[^\n]*")/g, '<span class="cm-string">$1</span>')
    .replace(/\b(re|match|search|find|group|compile|sub|exec|print|if|else|elif|for|while|return|in|not|and|or|True|False|None)\b/g, '<span class="cm-keyword">$1</span>')
    .replace(/\b(\d+\.?\d*)\b/g, '<span class="cm-number">$1</span>')
}

onMounted(() => loadVecRules())
</script>

<style scoped>
/* 2026-07-28 Phase 2 cleanup:
   表格迁 <el-table> / 加载走 v-loading / 空态走 empty-text / 3 卡片删(原本是参考用,从未挂上)。
   已删除: .vec-stat-cards / .vec-stat-card* / .vec-stat-label / .vec-stat-value /
            .vec-stat-rows / .vec-stat-row / .vec-stat-name / .vec-stat-l3 / .vec-stat-count /
            .vec-stat-bar / .vec-stat-bar-fill / .vec-stat-empty / .vec-stat-meta-line / .ctx-muted /
            .vec-loading / .vec-spinner / .vec-table / .vec-row / .vec-row-head / .vec-row-data /
            .vec-cell / .col-id / .vec-empty* / .vec-date 等。
   保留: @keyframes spin(全局可能复用)。 */

/* ── 页面容器 ── */
.ctx-page {
  padding: 0 28px 64px;
  color: var(--text, #1e293b);
  font-size: 13px;
}

/* ── 激活筛选 chips ── */
.vec-chips {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
  padding: 10px 14px;
  margin-bottom: 12px;
  background: linear-gradient(180deg, rgba(37,99,235,0.05), rgba(37,99,235,0.02));
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 8px;
  font-size: 12px;
}
.vec-chips-label {
  color: var(--text-3, #64748b);
  font-weight: 600;
  margin-right: 4px;
}
.vec-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px;
  background: #ffffff;
  color: var(--primary, #2563eb);
  border: 1px solid rgba(37,99,235,0.25);
  border-radius: 999px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.15s;
}
.vec-chip:hover {
  background: rgba(37,99,235,0.1);
  border-color: var(--primary, #2563eb);
}
.vec-chip-x {
  font-size: 14px;
  font-weight: 700;
  color: rgba(37,99,235,0.5);
}
.vec-chip:hover .vec-chip-x { color: var(--primary, #2563eb); }
.vec-chips-clear-all {
  margin-left: auto;
  padding: 4px 12px;
  background: transparent;
  color: var(--text-3, #64748b);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.15s;
}
.vec-chips-clear-all:hover {
  background: rgba(220,38,38,0.08);
  color: #dc2626;
  border-color: rgba(220,38,38,0.3);
}

/* ── Toolbar ── */
.vec-toolbar {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px;
  margin-bottom: 12px;
  background: var(--surface-2, #f8fafc);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
}
.vec-toolbar-main {
  display: flex; align-items: center; gap: 8px;
  flex: 1; min-width: 0; flex-wrap: nowrap;
  overflow-x: auto;
  scrollbar-width: thin;
}
.vec-toolbar-main::-webkit-scrollbar { height: 6px; }
.vec-toolbar-main::-webkit-scrollbar-thumb { background: rgba(15,23,42,0.18); border-radius: 3px; }
.vec-toolbar-side {
  flex-shrink: 0;
}
.vec-input {
  background: #ffffff;
  color: var(--text, #1e293b);
  border: 1px solid rgba(15,23,42,0.1);
  border-radius: var(--radius-sm, 6px);
  padding: 7px 10px;
  font-size: 13px;
  outline: none;
  transition: all 0.15s;
  font-family: inherit;
}
.vec-input:focus { border-color: var(--primary, #2563eb); box-shadow: 0 0 0 3px rgba(37,99,235,0.2); }
.vec-input:not(.vec-date) { flex: 1 1 200px; max-width: 380px; min-width: 140px; }
.vec-clear-btn {
  width: 28px; height: 30px;
  background: transparent;
  border: 1px solid rgba(15,23,42,0.1);
  color: var(--text-3);
  border-radius: 6px;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
}
.vec-clear-btn:hover { background: rgba(220,38,38,0.06); color: #dc2626; border-color: rgba(220,38,38,0.3); }
.vec-help-btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 7px 12px;
  background: rgba(37,99,235,0.06);
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 8px;
  color: var(--primary, #2563eb);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.18s;
}
.vec-help-btn:hover { background: rgba(37,99,235,0.12); }
.vec-help-btn.active { background: rgba(37,99,235,0.14); }

/* ── 帮助区 ── */
.vec-help {
  background: var(--surface-2, #f8fafc);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-2, #475569);
}
.vec-help-grid { display: flex; flex-direction: column; gap: 8px; }
.vec-help-row b { color: var(--text, #1e293b); margin-right: 4px; }
.vec-help-row code {
  background: rgba(37,99,235,0.08);
  color: var(--primary, #2563eb);
  padding: 1px 5px;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
  font-size: 11px;
}

/* ── 主表格(el-table 容器外壳) ── */
.vec-table-wrap {
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}

/* el-table 列内容排版 */
.vec-attr-tag {
  display: inline-block;
  background: rgba(37,99,235,0.1);
  color: var(--primary);
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 5px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
}
.vec-pattern {
  font-family: 'Courier New', monospace;
  font-size: 11.5px;
  background: rgba(37,99,235,0.06);
  color: var(--primary);
  border: 1px solid rgba(37,99,235,0.12);
  border-radius: 4px;
  padding: 2px 6px;
  font-weight: 600;
  word-break: break-all;
  white-space: normal;
  display: inline-block;
  max-width: 100%;
}
.vec-code-block {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 5px;
  padding: 6px 8px;
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: #c9d1d9;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
  max-height: 100px;
  overflow-y: auto;
  width: 100%;
}
.vec-code-block .cm-comment { color: #8b949e; font-style: italic; }
.vec-code-block .cm-string { color: #a5d6ff; }
.vec-code-block .cm-keyword { color: #ff7b72; font-weight: 600; }
.vec-code-block .cm-number { color: #79c0ff; }

/* ── 分页 — 沿用全局 .page-btn ── */
.vec-pagination {
  position: sticky;
  bottom: 0;
  display: flex; align-items: center; justify-content: center;
  gap: 5px;
  padding: 12px 18px;
  margin-top: 12px;
  background: rgba(241,245,249,0.95);
  backdrop-filter: blur(8px);
  border-top: 1px solid rgba(15,23,42,0.06);
  border-radius: 10px;
}

/* ── Transition ── */
.slide-down-enter-active, .slide-down-leave-active { transition: all 0.2s ease; }
.slide-down-enter-from, .slide-down-leave-to { opacity: 0; transform: translateY(-6px); }

/* ── 响应式(沿用 @media 框架,内仅保留 .vec-toolbar-main 移动端规则) ── */
@media (max-width: 768px) {
  .vec-toolbar-main { width: 100%; }
}
</style>
