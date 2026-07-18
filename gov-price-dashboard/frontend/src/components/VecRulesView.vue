<template>
  <div class="ctx-page">
    <!-- PageHeader (matching /taxonomy flat variant) -->
    <PageHeader
      variant="flat"
      title="规格规则库"
      subtitle="存储在 <code>breed_spec_rules.db</code>（SQLite + Blob），ETL DWD→DWS 阶段 3 AI 自动回写；本页支持 <code>pattern+attr+code</code> 多维检索"
      :stats="[
        { label: '规则总数', value: fmt.int(vecRules.total) },
        { label: '属性种类', value: vecAttrOptions.length },
        { label: 'L3 覆盖', value: vecL3Options.length, tone: vecL3Options.length > 0 ? 'ok' : 'mute' },
        { label: '当前页', value: `${vecRules.page} / ${vecRules.pages || 1}` },
      ]"
    />

    <!-- 3-column stat cards (Top attrs / Top L3 / Query context) — 借鉴 /taxonomy 的 .ctx-conf-cards -->
    <div class="vec-stat-cards">
      <!-- 属性分布 -->
      <div class="vec-stat-card">
        <div class="vec-stat-card-head">
          <span class="vec-stat-label">属性 Top {{ topAttrs.length }}</span>
          <span class="vec-stat-value">{{ fmt.int(vecRules.total) }}</span>
        </div>
        <div class="vec-stat-rows">
          <div v-for="row in topAttrs" :key="row.key" class="vec-stat-row">
            <span class="vec-stat-name">{{ row.key }}</span>
            <span class="vec-stat-count">{{ fmt.int(row.count) }}</span>
            <span class="vec-stat-bar"><span class="vec-stat-bar-fill" :style="{ width: pct(row.count) + '%' }"></span></span>
          </div>
          <div v-if="!topAttrs.length" class="vec-stat-empty">暂无属性分布数据</div>
        </div>
      </div>

      <!-- L3 分布 -->
      <div class="vec-stat-card">
        <div class="vec-stat-card-head">
          <span class="vec-stat-label">L3 Top {{ topL3s.length }}</span>
          <span class="vec-stat-value">{{ vecL3Options.length }}</span>
        </div>
        <div class="vec-stat-rows">
          <div v-for="row in topL3s" :key="row.key" class="vec-stat-row">
            <span class="vec-stat-l3">{{ row.key }}</span>
            <span class="vec-stat-count">{{ fmt.int(row.count) }}</span>
            <span class="vec-stat-bar"><span class="vec-stat-bar-fill" :style="{ width: pct(row.count) + '%' }"></span></span>
          </div>
          <div v-if="!topL3s.length" class="vec-stat-empty">暂无 L3 覆盖</div>
        </div>
      </div>

      <!-- 查询态 -->
      <div class="vec-stat-card vec-stat-card-meta">
        <div class="vec-stat-card-head">
          <span class="vec-stat-label">查询状态</span>
          <span class="vec-stat-value">{{ activeChips.length ? '已筛选' : '全部' }}</span>
        </div>
        <div class="vec-stat-rows">
          <template v-if="!activeChips.length">
            <div class="vec-stat-meta-line">无任何筛选条件</div>
            <div class="vec-stat-meta-line ctx-muted">展示全部 <code>{{ fmt.int(vecRules.total) }}</code> 条规则</div>
          </template>
          <template v-else>
            <div v-for="chip in activeChips" :key="chip.key" class="vec-stat-meta-line">
              <code>{{ chip.label }}</code>
            </div>
          </template>
        </div>
      </div>
    </div>

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
        <input type="date" class="vec-input vec-date" v-model="vecDateFrom" @change="loadVecRules(1)" title="起始日期 (created_at)" />
        <input type="date" class="vec-input vec-date" v-model="vecDateTo" @change="loadVecRules(1)" title="结束日期 (created_at)" />
        <button v-if="vecDateFrom || vecDateTo" class="vec-clear-btn" @click="clearDateRange" title="清除日期范围">×</button>
        <CustomSelect
          v-model="vecAttrFilter"
          :options="vecAttrOptions.map(o => ({ key: o.key, label: o.key, count: o.count }))"
          placeholder="全部属性"
          :count-suffix="true"
          @change="loadVecRules(1)"
        />
        <CustomSelect
          v-model="vecCatFilter"
          :options="vecCatOptions.map(o => ({ key: o.key, label: o.key, count: o.count }))"
          placeholder="全部分类"
          :count-suffix="true"
          @change="loadVecRules(1)"
        />
        <CustomSelect
          v-model="vecL3Filter"
          :options="vecL3Options.map(o => ({ key: o.key, label: o.key, count: o.count }))"
          placeholder="全部 L3"
          :count-suffix="true"
          @change="loadVecRules(1)"
        />
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
          <div class="vec-help-row"><b>怎么检索</b>关键字（pattern / note / code）+ 属性 + 分类 + L3 + 日期范围 多维组合。</div>
          <div class="vec-help-row"><b>怎么新增</b>暂无人工入口，自动从 AI 解析成功后回写；脏数据可通过 <code>DELETE FROM breed_spec_rules</code> 清理。</div>
          <div class="vec-help-row"><b>字段含义</b><code>attr</code> 业务属性名；<code>pattern</code> 不带 <code>r</code> 前缀的 regex；<code>code</code> 单行或 <code>\\n</code> 多行 Python；<code>l3</code> 召回 +0.40 加权。</div>
        </div>
      </div>
    </Transition>

    <!-- 主表格 -->
    <div class="vec-table-wrap">
      <div v-if="vecLoading" class="vec-loading">
        <div class="vec-spinner"></div>
        <span>加载中...</span>
      </div>

      <div v-else class="vec-table" :style="{ gridTemplateColumns: GRID_COLS }">
        <!-- Header -->
        <div class="vec-row vec-row-head">
          <div class="vec-cell col-id">#</div>
          <div class="vec-cell col-breed">breed</div>
          <div class="vec-cell col-attr">属性</div>
          <div class="vec-cell col-l3">L3 分项</div>
          <div class="vec-cell col-pattern">pattern</div>
          <div class="vec-cell col-code">code</div>
          <div class="vec-cell col-note">note</div>
          <div class="vec-cell col-date">创建时间</div>
        </div>

        <!-- Data rows -->
        <div v-for="(r, idx) in vecRules.items" :key="r.id" class="vec-row vec-row-data">
          <div class="vec-cell col-id">{{ (vecRules.page - 1) * vecPageSize + idx + 1 }}</div>
          <div class="vec-cell col-breed" :title="r.breed">{{ r.breed || '—' }}</div>
          <div class="vec-cell col-attr"><span class="vec-attr-tag">{{ r.attr || '—' }}</span></div>
          <div class="vec-cell col-l3">{{ r.l3 || '—' }}</div>
          <div class="vec-cell col-pattern"><code class="vec-pattern" :title="r.pattern">{{ r.pattern }}</code></div>
          <div class="vec-cell col-code"><pre class="vec-code-block" v-html="highlightPy(r.code || '')"></pre></div>
          <div class="vec-cell col-note">{{ r.note || '—' }}</div>
          <div class="vec-cell col-date">{{ r.created_at ? r.created_at.slice(0, 19) : '—' }}</div>
        </div>

        <!-- Empty state -->
        <div v-if="!vecLoading && !vecRules.items?.length" class="vec-empty">
          <div class="vec-empty-icon">📭</div>
          <div class="vec-empty-title">{{ activeChips.length ? '没有匹配当前筛选的规则' : '暂无规则' }}</div>
          <div class="vec-empty-hint">{{ activeChips.length ? '点击右上角【全部清除】或单独移除筛选条件' : 'sync_dws stage 3 AI 解析后会写入规则库' }}</div>
        </div>
      </div>
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

import CustomSelect from './CustomSelect.vue'
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
const vecAttrFilter = ref('')
const vecCatFilter = ref('')
const vecL3Filter = ref('')
const vecDateFrom = ref('')
const vecDateTo = ref('')
const vecOrder = ref('desc')
const vecAttrOptions = ref([])
const vecCatOptions = ref([])
const vecL3Options = ref([])
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

// Top 8 attrs / L3（按 count 降序）— 用作 stat cards 数据源
const topAttrs = computed(() =>
  [...(vecAttrOptions.value || [])]
    .sort((a, b) => b.count - a.count)
    .slice(0, 8)
)
const topL3s = computed(() =>
  [...(vecL3Options.value || [])]
    .sort((a, b) => b.count - a.count)
    .slice(0, 8)
)

// 激活筛选条件汇总（用于顶部 chips 横条 + 卡片展示）
const activeChips = computed(() => {
  const cs = []
  if (vecSearch.value) cs.push({ key: 'search', label: '🔍 「' + vecSearch.value + '」', clear: () => { vecSearch.value = '' } })
  if (vecDateFrom.value) cs.push({ key: 'date_from', label: '📅 起「' + vecDateFrom.value + '」', clear: () => { vecDateFrom.value = '' } })
  if (vecDateTo.value) cs.push({ key: 'date_to', label: '📅 止「' + vecDateTo.value + '」', clear: () => { vecDateTo.value = '' } })
  if (vecAttrFilter.value) cs.push({ key: 'attr', label: '属性「' + vecAttrFilter.value + '」', clear: () => { vecAttrFilter.value = '' } })
  if (vecCatFilter.value) cs.push({ key: 'cat', label: '分类「' + vecCatFilter.value + '」', clear: () => { vecCatFilter.value = '' } })
  if (vecL3Filter.value) cs.push({ key: 'l3', label: 'L3「' + vecL3Filter.value + '」', clear: () => { vecL3Filter.value = '' } })
  return cs
})

function pct(v) {
  const arr = topAttrs.value.length > topL3s.value.length ? topAttrs.value : topL3s.value
  const total = Math.max(1, ...arr.map(r => r.count || 0))
  return ((v / total) * 100).toFixed(1)
}

// ── 交互 ──
function clearOne(chip) {
  chip.clear()
  loadVecRules(1)
}

function clearAllFilters() {
  vecSearch.value = ''
  vecDateFrom.value = ''
  vecDateTo.value = ''
  vecAttrFilter.value = ''
  vecCatFilter.value = ''
  vecL3Filter.value = ''
  loadVecRules(1)
}

function clearDateRange() {
  vecDateFrom.value = ''
  vecDateTo.value = ''
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
    if (vecAttrFilter.value) params.attr = vecAttrFilter.value
    if (vecCatFilter.value) params.category = vecCatFilter.value
    if (vecL3Filter.value) params.l3 = vecL3Filter.value
    if (vecDateFrom.value) params.date_from = vecDateFrom.value
    if (vecDateTo.value) params.date_to = vecDateTo.value
    const res = await axios.get(`${API}/stats/rules-vector`, { params })
    vecRules.value = res.data || {}
    vecAttrOptions.value = res.data.attr_options || []
    vecCatOptions.value = res.data.category_options || []
    vecL3Options.value = res.data.l3_options || []
  } catch (e) {
    console.warn('rules-vector failed', e)
  } finally {
    vecLoading.value = false
  }
}

// ── URL query 同步 (date_from / date_to 直达链接) ──
const route = useRoute()
const router = useRouter()
if (route.query.date_from) vecDateFrom.value = String(route.query.date_from)
if (route.query.date_to) vecDateTo.value = String(route.query.date_to)

watch([vecDateFrom, vecDateTo], () => {
  const q = { ...route.query }
  if (vecDateFrom.value) q.date_from = vecDateFrom.value
  else delete q.date_from
  if (vecDateTo.value) q.date_to = vecDateTo.value
  else delete q.date_to
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
/* ── 借鉴 /taxonomy 的设计 token + 页面容器 ── */
.ctx-page {
  padding: 0 28px 64px;
  color: var(--text, #1e293b);
  font-size: 13px;
}

/* ── 3 卡片行（借鉴 /taxonomy .ctx-conf-cards） ── */
.vec-stat-cards {
  display: grid;
  grid-template-columns: 1.3fr 1.3fr 1fr;
  gap: 14px;
  margin: 16px 0;
}
.vec-stat-card,
.vec-stat-card-meta {
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, rgba(15,23,42,0.08));
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
  display: flex;
  flex-direction: column;
  min-height: 160px;
}
.vec-stat-card-head {
  display: flex; align-items: baseline; justify-content: space-between;
  margin-bottom: 12px;
}
.vec-stat-label {
  font-size: 11px; font-weight: 600; color: var(--text-3, #64748b);
  text-transform: uppercase; letter-spacing: 0.05em;
}
.vec-stat-value {
  font-size: 22px; font-weight: 700; color: var(--text, #1e293b);
  font-family: 'Courier New', monospace;
}
.vec-stat-rows { flex: 1; overflow-y: auto; max-height: 220px; }
.vec-stat-row {
  display: grid;
  grid-template-columns: 1fr auto 50px;
  align-items: center;
  gap: 10px;
  padding: 5px 0;
  font-size: 12px;
  border-bottom: 1px dashed rgba(15,23,42,0.04);
}
.vec-stat-row:last-child { border-bottom: none; }
.vec-stat-name,
.vec-stat-l3 {
  color: var(--text, #1e293b);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vec-stat-l3 {
  font-family: 'Courier New', monospace;
  font-size: 11.5px;
  color: var(--primary, #2563eb);
}
.vec-stat-count {
  font-family: 'Courier New', monospace;
  font-weight: 700;
  font-size: 12px;
  text-align: right;
}
.vec-stat-bar {
  position: relative;
  height: 6px;
  border-radius: 3px;
  background: var(--surface-3, #e2e8f0);
  overflow: hidden;
  opacity: 0.6;
}
.vec-stat-bar-fill {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--primary, #2563eb), rgba(37,99,235,0.6));
  border-radius: 3px;
  transition: width 0.3s ease;
}
.vec-stat-empty,
.vec-stat-meta-line,
.ctx-muted {
  color: var(--text-3, #64748b);
  font-size: 12px;
  padding: 5px 0;
}
.vec-stat-meta-line code {
  background: rgba(37,99,235,0.1);
  color: var(--primary, #2563eb);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 11.5px;
  font-weight: 600;
  display: inline-block;
  margin-right: 4px;
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
  flex: 1; min-width: 0; flex-wrap: wrap;
}
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
.vec-input:not(.vec-date) { flex: 1 1 240px; max-width: 380px; min-width: 200px; }
.vec-date {
  width: 132px;
  font-size: 12px;
  color: var(--text-3);
  cursor: pointer;
}
input.vec-input.vec-date { background: var(--surface, #ffffff); }
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

/* ── 主表格 ── */
.vec-table-wrap {
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.vec-loading {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 60px 20px;
  color: var(--text-3);
  font-size: 13px;
}
.vec-spinner {
  width: 18px; height: 18px;
  border: 2px solid rgba(15,23,42,0.08);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.vec-table {
  display: grid;
  font-size: 12.5px;
  overflow-x: auto;
}
.vec-row {
  display: contents;
}
.vec-row-head .vec-cell {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--surface-2, #f8fafc);
  border-bottom: 1px solid var(--border);
  padding: 12px 10px;
  position: sticky; top: 0;
  z-index: 2;
}
.vec-row-data .vec-cell {
  padding: 10px;
  border-bottom: 1px solid var(--surface-2, rgba(15,23,42,0.04));
  display: flex; align-items: center;
  min-width: 0;
  overflow: hidden;
}
.vec-row-data:hover .vec-cell {
  background: rgba(37,99,235,0.03);
}
.vec-cell {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.col-id { justify-content: center; font-family: 'Courier New', monospace; font-size: 11px; color: var(--text-3); }
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

/* ── 空态 ── */
.vec-empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-3);
  grid-column: 1 / -1;
}
.vec-empty-icon { font-size: 48px; margin-bottom: 12px; opacity: 0.6; }
.vec-empty-title { font-size: 14px; font-weight: 600; color: var(--text-2); margin-bottom: 6px; }
.vec-empty-hint { font-size: 12px; color: var(--text-3); max-width: 480px; margin: 0 auto; }

/* ── 分页 — 沿用全局 .pagination / .page-btn ── */
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

/* ── 响应式 ── */
@media (max-width: 1200px) {
  .vec-stat-cards { grid-template-columns: 1fr 1fr; }
  .vec-stat-card-meta { grid-column: 1 / -1; }
}
@media (max-width: 768px) {
  .vec-stat-cards { grid-template-columns: 1fr; }
  .vec-toolbar-main { width: 100%; }
}
</style>
