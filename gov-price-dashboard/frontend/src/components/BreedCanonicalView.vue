<template>
  <div class="ctx-page">
    <!-- PageHeader (minimal — title + subtitle only, 与 vec 一致) -->
    <PageHeader
      variant="flat"
      title="品种归一后台"
      subtitle="存储于 <code>breed_canonical.db</code> · 只读浏览 · 写入由 v3 ETL + Dify AI + 人工修正脚本联合维护"
    />

    <!-- Active filter chips (借鉴 vec-chips — 白底蓝边) -->
    <Transition name="slide-down">
      <div class="canon-chips" v-if="activeChips.length">
        <span class="canon-chips-label">当前筛选</span>
        <span
          v-for="chip in activeChips" :key="chip.key"
          class="canon-chip" @click="clearOne(chip)"
          :title="`移除 ${chip.label}`"
        >{{ chip.label }}<span class="canon-chip-x">×</span></span>
        <button class="canon-chips-clear-all" @click="clearAllFilters" title="一键清除所有筛选">全部清除</button>
      </div>
    </Transition>

    <!-- Toolbar (借鉴 vec-toolbar) -->
    <div class="canon-toolbar">
      <div class="canon-toolbar-main">
        <input class="canon-input" v-model="search" placeholder="🔍 搜索 breed_clean / normalized_breed / note..." @input="debounceReload(1)" />
        <select class="canon-input canon-select" v-model="source" @change="reload(1)">
          <option value="">source (全部)</option>
          <option v-for="s in (stats?.by_source || [])" :key="s[0]" :value="s[0]">{{ s[0] }} ({{ s[1] }})</option>
        </select>
        <select class="canon-input canon-select" v-model="l3" @change="reload(1)">
          <option value="">l3_code (全部)</option>
          <option v-for="lc in (stats?.top10_l3 || [])" :key="lc[0]" :value="lc[0]">{{ lc[0] }} ({{ lc[1] }})</option>
        </select>
        <label class="canon-toggle" title="只看 l3_code 为空的记录">
          <input type="checkbox" v-model="nullL3" @change="reload(1)" />只看 NULL l3
        </label>
        <button v-if="hasFilter" class="canon-clear-btn" @click="clearAllFilters" title="清除所有筛选">×</button>
      </div>
      <div class="canon-toolbar-side">
        <button class="canon-help-btn" :class="{ active: showHelp }" @click="showHelp = !showHelp">
          {{ showHelp ? '🔼 收起说明' : '📖 使用说明' }}
        </button>
      </div>
    </div>

    <!-- Help -->
    <Transition name="slide-down">
      <div class="canon-help" v-if="showHelp">
        <div class="canon-help-grid">
          <div class="canon-help-row"><b>是什么</b>存储于 <code>skills/data/breed_canonical.db</code> 的品种→L3 映射表。</div>
          <div class="canon-help-row"><b>怎么检索</b>关键字（breed_clean / normalized_breed / note）模糊匹配 + source / l3_code 精确过滤 + NULL l3 单独筛选。</div>
          <div class="canon-help-row"><b>source 含义</b><code>etl_v3_sqlite</code> 自动归一量最大 · <code>ai_dify</code> AI 兜底 · <code>manual_fix_*</code> 人工校准</div>
          <div class="canon-help-row"><b>置信度</b>≥0.95 高 · 0.85–0.95 中 · 0.5–0.85 低 · &lt;0.5 不可信（需要重映射）</div>
          <div class="canon-help-row"><b>写入路径</b>本页只读。写入由 <code>gov-price-normalization</code> CLI + 治理脚本（<code>manual_fix_*</code>）负责。</div>
        </div>
      </div>
    </Transition>

    <!-- Main table (CSS Grid + inline gridTemplateColumns, 与 vec 一致) -->
    <div class="canon-table-wrap">
      <div v-if="loading" class="canon-loading">
        <div class="canon-spinner"></div>
        <span>加载中…</span>
      </div>
      <div v-else class="canon-table" :style="{ gridTemplateColumns: GRID_COLS }">
        <div class="canon-row canon-row-head">
          <div class="canon-cell col-id">#</div>
          <div class="canon-cell col-breed text-left">breed_clean</div>
          <div class="canon-cell col-norm text-left">normalized_breed</div>
          <div class="canon-cell col-l3">l3_code</div>
          <div class="canon-cell col-conf">confidence</div>
          <div class="canon-cell col-source">source</div>
          <div class="canon-cell col-note text-left">note</div>
          <div class="canon-cell col-date">updated_at</div>
        </div>
        <div v-for="(r, idx) in rows" :key="r.breed_clean" class="canon-row canon-row-data">
          <div class="canon-cell col-id">{{ (page - 1) * size + idx + 1 }}</div>
          <div class="canon-cell col-breed text-left canon-cell-strong" :title="r.breed_clean">{{ r.breed_clean }}</div>
          <div class="canon-cell col-norm text-left" :title="r.normalized_breed">{{ r.normalized_breed }}</div>
          <div class="canon-cell col-l3">
            <span v-if="r.l3_code" class="canon-l3-pill">{{ r.l3_code }}</span>
            <span v-else class="canon-l3-pill canon-l3-pill-warn">UNCLASSIFIED</span>
          </div>
          <div class="canon-cell col-conf">
            <span class="canon-conf" :class="confClass(r.confidence)">{{ r.confidence.toFixed(2) }}</span>
          </div>
          <div class="canon-cell col-source">
            <span class="canon-source-tag">{{ r.source }}</span>
          </div>
          <div class="canon-cell col-note text-left" :title="r.note">{{ r.note || '—' }}</div>
          <div class="canon-cell col-date">{{ r.updated_at ? r.updated_at.slice(0, 19) : '—' }}</div>
        </div>
        <div v-if="!loading && !rows.length" class="canon-empty">
          <div class="canon-empty-icon">📭</div>
          <div class="canon-empty-title">{{ activeChips.length ? '没有匹配当前筛选的映射' : '暂无映射' }}</div>
          <div class="canon-empty-hint">{{ activeChips.length ? '点击【全部清除】或单独移除筛选条件' : 'check breed_canonical.db 是否存在 / 是否有数据' }}</div>
        </div>
      </div>
    </div>

    <!-- Pagination (借鉴 vec-pagination: 跳至 N 页 + 每页 N 条) -->
    <div class="canon-pagination" v-if="pages > 1">
      <button class="page-btn nav" :disabled="page <= 1" @click="reload(page - 1)">‹</button>
      <button
        v-for="p in pageRange" :key="p"
        class="page-btn" :class="{ active: p === page, ellipsis: p === '...' }"
        :disabled="p === '...'" @click="p !== '...' && reload(p)"
      >{{ p }}</button>
      <button class="page-btn nav" :disabled="page >= pages" @click="reload(page + 1)">›</button>
      <div class="page-jump-wrap">
        <span>跳至</span>
        <input class="page-jump" v-model.number="jumpPage" @keyup.enter="goToPage" type="number" min="1" :max="pages" />
        <span>页</span>
      </div>
      <div class="page-size-wrap">
        <span>每页</span>
        <select class="page-size-select" v-model.number="size" @change="reload(1)">
          <option v-for="s in pageSizeOptions" :key="s" :value="s">{{ s }}</option>
        </select>
        <span>条</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import PageHeader from './PageHeader.vue'

// 8 列 (id / breed / norm / l3 / conf / source / note / date) — 沿用 vec 的 fr 比例
const GRID_COLS = '52px minmax(140px, 1.4fr) minmax(140px, 1fr) minmax(110px, 1.1fr) minmax(110px, 1fr) minmax(140px, 1.2fr) minmax(220px, 2fr) minmax(150px, 1fr)'

const search = ref('')
const source = ref('')
const l3 = ref('')
const nullL3 = ref(false)
const page = ref(1)
const size = ref(20)
const pageSizeOptions = [20, 50, 100]
const jumpPage = ref(1)
const total = ref(0)
const pages = ref(0)
const rows = ref([])
const stats = ref(null)
const loading = ref(false)
const showHelp = ref(false)

function confClass(c) {
  if (c >= 0.95) return 'high'
  if (c >= 0.85) return 'mid'
  if (c >= 0.5) return 'low'
  return 'bad'
}

// ── chips ──
const activeChips = computed(() => {
  const chips = []
  if (search.value.trim()) chips.push({ key: 'search', label: `🔍 「${search.value.trim()}」` })
  if (source.value) chips.push({ key: 'source', label: `📦 ${source.value}` })
  if (l3.value) chips.push({ key: 'l3', label: `🏷 ${l3.value}` })
  if (nullL3.value) chips.push({ key: 'nullL3', label: '⚠️ 只看 NULL l3' })
  return chips
})

const hasFilter = computed(() => activeChips.value.length > 0)

function clearOne(chip) {
  if (chip.key === 'search') search.value = ''
  else if (chip.key === 'source') source.value = ''
  else if (chip.key === 'l3') l3.value = ''
  else if (chip.key === 'nullL3') nullL3.value = false
  reload(1)
}

function clearAllFilters() {
  search.value = ''
  source.value = ''
  l3.value = ''
  nullL3.value = false
  reload(1)
}

// ── page range ──
const pageRange = computed(() => {
  const p = pages.value
  const cur = page.value
  if (!p) return []
  if (p <= 7) return Array.from({ length: p }, (_, i) => i + 1)
  const set = new Set([1, p, cur, cur - 1, cur + 1])
  const list = [...set].filter(n => n >= 1 && n <= p).sort((a, b) => a - b)
  const out = []
  for (let i = 0; i < list.length; i++) {
    if (i > 0 && list[i] - list[i - 1] > 1) out.push('...')
    out.push(list[i])
  }
  return out
})

function goToPage() {
  const p = Number(jumpPage.value)
  if (p >= 1 && p <= pages.value) reload(p)
  else jumpPage.value = page.value
}

// ── data loading ──
let debounceTimer = null
function debounceReload(p) {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => reload(p || 1), 300)
}

async function loadStats() {
  try {
    const r = await fetch('/api/canon/breeds/stats')
    if (r.ok) stats.value = await r.json()
  } catch (e) { console.error('[canon] stats load failed', e) }
}

async function reload(p) {
  if (p) page.value = p
  loading.value = true
  const params = new URLSearchParams({ page: page.value, size: size.value })
  if (search.value.trim()) params.set('search', search.value.trim())
  if (source.value) params.set('source', source.value)
  if (l3.value) params.set('l3_code', l3.value)
  if (nullL3.value) params.set('null_l3', 'true')
  try {
    const r = await fetch('/api/canon/breeds?' + params)
    if (!r.ok) { rows.value = []; total.value = 0; pages.value = 0; return }
    const d = await r.json()
    rows.value = d.rows || []
    total.value = d.total || 0
    pages.value = Math.ceil(total.value / size.value) || 1
    jumpPage.value = page.value
  } catch (e) { console.error('[canon] breeds load failed', e) }
  finally { loading.value = false }
}

onMounted(() => { loadStats(); reload(1) })
</script>

<style scoped>
.ctx-page {
  padding: 0 28px 64px;
  color: var(--text, #1e293b);
  font-size: 13px;
}

/* ── Active filter chips (白底蓝边 — 借鉴 vec-chip) ── */
.canon-chips {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
  padding: 10px 14px;
  margin-bottom: 12px;
  background: linear-gradient(180deg, rgba(37,99,235,0.05), rgba(37,99,235,0.02));
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 8px;
  font-size: 12px;
}
.canon-chips-label {
  color: var(--text-3, #64748b);
  font-weight: 600;
  margin-right: 4px;
}
.canon-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px;
  background: #ffffff;
  color: var(--primary, #2563eb);
  border: 1px solid rgba(37,99,235,0.25);
  border-radius: 999px;
  cursor: pointer;
  font-size: 12px; font-weight: 500;
  transition: all 0.15s;
}
.canon-chip:hover {
  background: rgba(37,99,235,0.1);
  border-color: var(--primary, #2563eb);
}
.canon-chip-x {
  font-size: 14px; font-weight: 700;
  color: rgba(37,99,235,0.5);
}
.canon-chip:hover .canon-chip-x { color: var(--primary, #2563eb); }
.canon-chips-clear-all {
  margin-left: auto;
  padding: 4px 12px;
  background: transparent;
  color: var(--text-3, #64748b);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.canon-chips-clear-all:hover {
  background: rgba(220,38,38,0.08);
  color: #dc2626;
  border-color: rgba(220,38,38,0.3);
}

/* ── Toolbar (借鉴 vec-toolbar) ── */
.canon-toolbar {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px;
  margin-bottom: 12px;
  background: var(--surface-2, #f8fafc);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
}
.canon-toolbar-main {
  display: flex; align-items: center; gap: 8px;
  flex: 1; min-width: 0;
  overflow-x: auto; scrollbar-width: thin;
}
.canon-toolbar-main::-webkit-scrollbar { height: 6px; }
.canon-toolbar-main::-webkit-scrollbar-thumb { background: rgba(15,23,42,0.18); border-radius: 3px; }
.canon-toolbar-side {
  display: flex; align-items: center; gap: 8px; flex-shrink: 0;
}
.canon-input {
  background: #fff;
  color: var(--text, #1e293b);
  border: 1px solid rgba(15,23,42,0.1);
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 13px;
  outline: none;
  transition: all 0.15s;
  font-family: inherit;
}
.canon-input:focus { border-color: var(--primary, #2563eb); box-shadow: 0 0 0 3px rgba(37,99,235,0.2); }
.canon-toolbar-main > .canon-input:not(.canon-select) { flex: 1 1 220px; max-width: 360px; min-width: 160px; }
.canon-select { cursor: pointer; min-width: 130px; }
.canon-toggle {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 13px; color: var(--text-2, #475569);
  cursor: pointer; white-space: nowrap; padding: 0 4px;
}
.canon-clear-btn {
  width: 28px; height: 30px;
  background: transparent;
  border: 1px solid rgba(15,23,42,0.1);
  color: var(--text-3);
  border-radius: 6px;
  cursor: pointer; font-size: 16px; line-height: 1;
}
.canon-clear-btn:hover { background: rgba(220,38,38,0.06); color: #dc2626; border-color: rgba(220,38,38,0.3); }

.canon-help-btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 7px 12px;
  background: rgba(37,99,235,0.06);
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 8px;
  color: var(--primary, #2563eb);
  font-size: 12px; font-weight: 500;
  cursor: pointer; white-space: nowrap;
  transition: all 0.18s;
}
.canon-help-btn:hover { background: rgba(37,99,235,0.12); }
.canon-help-btn.active { background: rgba(37,99,235,0.14); }

/* ── Help (借鉴 vec-help) ── */
.canon-help {
  background: var(--surface-2, #f8fafc);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
  font-size: 12.5px; line-height: 1.6;
  color: var(--text-2, #475569);
}
.canon-help-grid { display: flex; flex-direction: column; gap: 8px; }
.canon-help-row b { color: var(--text, #1e293b); margin-right: 4px; }
.canon-help-row code {
  background: rgba(37,99,235,0.08);
  color: var(--primary, #2563eb);
  padding: 1px 5px;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
  font-size: 11px;
}

/* ── Main table (CSS Grid, 借鉴 vec-table) ── */
.canon-table-wrap {
  background: var(--surface, #fff);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
  overflow: auto;
  max-height: calc(100vh - 540px);
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.canon-loading {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 60px 20px;
  color: var(--text-3);
  font-size: 13px;
}
.canon-spinner {
  width: 18px; height: 18px;
  border: 2px solid rgba(15,23,42,0.08);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: canonSpin 0.7s linear infinite;
}
@keyframes canonSpin { to { transform: rotate(360deg); } }

.canon-table {
  display: grid;
  font-size: 12.5px;
  min-width: 1200px;
}
.canon-row { display: contents; }
.canon-row-head .canon-cell {
  font-size: 11px; font-weight: 600;
  color: var(--text-3, #64748b);
  text-transform: uppercase; letter-spacing: 0.05em;
  background: var(--surface-2, #f8fafc);
  border-bottom: 1px solid var(--border);
  padding: 12px 10px;
  position: sticky; top: 0; z-index: 2;
}
.canon-row-data .canon-cell {
  padding: 10px;
  border-bottom: 1px solid rgba(15,23,42,0.04);
  display: flex; align-items: center;
  min-width: 0; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.canon-row-data:hover .canon-cell { background: rgba(37,99,235,0.03); }
.canon-cell { min-width: 0; }
.text-left { justify-content: flex-start; text-align: left; }
.col-id { justify-content: center; font-family: 'Courier New', monospace; font-size: 11px; color: var(--text-3); }
.col-breed { font-weight: 600; color: var(--text, #1e293b); }
.canon-cell-strong { font-weight: 600; color: #111827; }
.col-norm { color: var(--text-2, #475569); }

.canon-l3-pill {
  display: inline-block;
  padding: 1px 8px;
  background: rgba(37,99,235,0.1);
  color: var(--primary, #2563eb);
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 5px;
  font-size: 11px;
  font-family: 'Courier New', monospace;
  font-weight: 600;
  white-space: nowrap;
}
.canon-l3-pill-warn { background: #fef3c7; color: #92400e; border-color: #fde68a; }

.canon-conf {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'Courier New', monospace;
  font-weight: 600;
}
.canon-conf.high { background: #dcfce7; color: #166534; }
.canon-conf.mid  { background: #dbeafe; color: #1d4ed8; }
.canon-conf.low  { background: #fef3c7; color: #92400e; }
.canon-conf.bad  { background: #fee2e2; color: #991b1b; }

.canon-source-tag {
  display: inline-block;
  font-size: 11px;
  color: #4b5563;
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
  white-space: nowrap;
}

.col-note { color: var(--text-3); font-size: 12px; white-space: normal; line-height: 1.4; }
.col-date { color: var(--text-3); font-size: 11px; font-family: 'Courier New', monospace; }

/* Empty */
.canon-empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-3);
  grid-column: 1 / -1;
}
.canon-empty-icon { font-size: 48px; margin-bottom: 12px; opacity: 0.6; }
.canon-empty-title { font-size: 14px; font-weight: 600; color: var(--text-2); margin-bottom: 6px; }
.canon-empty-hint { font-size: 12px; color: var(--text-3); max-width: 480px; margin: 0 auto; }

/* ── Pagination (借鉴 vec-pagination) ── */
.canon-pagination {
  position: sticky;
  bottom: 0;
  display: flex; align-items: center; justify-content: center;
  gap: 8px;
  padding: 12px 18px;
  margin-top: 12px;
  background: rgba(241,245,249,0.95);
  backdrop-filter: blur(8px);
  border-top: 1px solid rgba(15,23,42,0.06);
  border-radius: 10px;
  flex-wrap: wrap;
}
.page-btn {
  min-width: 32px; height: 32px; padding: 0 8px;
  background: #fff; border: 1px solid rgba(15,23,42,0.08);
  border-radius: 6px;
  color: var(--text-2);
  font-size: 12px; font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}
.page-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.page-btn.active { background: var(--primary); color: #fff; border-color: var(--primary); }
.page-btn.ellipsis { border: none; background: transparent; cursor: default; }
.page-btn.nav { font-size: 14px; }
.page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.page-jump-wrap, .page-size-wrap {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12px; color: var(--text-3, #64748b);
  margin-left: 4px;
}
.page-jump {
  width: 50px; padding: 5px 6px;
  background: #fff;
  border: 1px solid rgba(15,23,42,0.1);
  border-radius: 6px;
  font-size: 12px; font-family: inherit;
  outline: none;
  text-align: center;
}
.page-jump:focus { border-color: var(--primary); }
.page-size-select {
  background: #fff;
  border: 1px solid rgba(15,23,42,0.1);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  outline: none;
}

/* ── Slide down transition ── */
.slide-down-enter-active, .slide-down-leave-active { transition: all 0.2s ease; }
.slide-down-enter-from, .slide-down-leave-to { opacity: 0; transform: translateY(-6px); }

</style>