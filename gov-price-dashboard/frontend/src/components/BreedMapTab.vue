<template>
  <!-- Toolbar -->
  <div class="ctx-toolbar">
    <div class="ctx-toolbar-left">
      <div class="ctx-search-wrap">
        <span class="ctx-search-icon">🔍</span>
        <input
          class="ctx-input"
          v-model="mapKeyword"
          placeholder="搜索品种 / L3 / GB50500..."
          @input="debounceLoadMap(1)"
        />
      </div>
      <select class="ctx-select" v-model="filterSource" @change="loadMap(1)">
        <option value="">来源 (全部)</option>
        <option v-for="s in sourceOpts" :key="s" :value="s">{{ sourceLabel(s) }}</option>
      </select>
      <select class="ctx-select" v-model="filterConfidence" @change="loadMap(1)">
        <option value="">置信度 (全部)</option>
        <option value="high">高 (≥0.85)</option>
        <option value="mid">中 (0.7–0.85)</option>
        <option value="low">低 (&lt;0.7)</option>
      </select>
      <button v-if="hasFilter" class="ctx-btn ctx-btn-ghost" @click="clearMapFilters">✕ 清空筛选</button>
      <span v-if="dateActive" class="ctx-date-chip" :title="`${dateFrom || '∞'} → ${dateTo || '∞'}`">
        📅 {{ dateFrom || '*' }} → {{ dateTo || '*' }}
      </span>
    </div>
    <div class="ctx-toolbar-right">
      <div class="ctx-density-toggle" title="行密度切换">
        <button :class="{ active: density === 'compact' }" @click="density = 'compact'">紧凑</button>
        <button :class="{ active: density === 'normal' }"  @click="density = 'normal'">默认</button>
        <button :class="{ active: density === 'loose' }"   @click="density = 'loose'">宽松</button>
      </div>
      <button class="ctx-btn ctx-btn-cyan" @click="exportCsv" :disabled="!mapRows.length">
        ⬇ 导出 CSV
      </button>
      <button class="ctx-btn ctx-btn-cyan" @click="showHelp = !showHelp">
        {{ showHelp ? '🔼 收起' : '📖 使用说明' }}
      </button>
    </div>
  </div>

  <!-- 使用说明 -->
  <Transition name="ctx-slide">
    <div class="ctx-help" v-if="showHelp">
      <div class="ctx-help-title">📖 品种映射说明</div>
      <div class="ctx-help-grid">
        <div class="ctx-help-item">
          <span class="ctx-help-key">是什么</span>
          <span class="ctx-help-val">
            品种名（<code>breed</code>）→ <code>L3</code> 分类的映射表<br/>
            DWS 阶段依赖它给每个品种贴分类标签，进而归一、跨城比价<br/>
            表本身由 <code>v3 ETL</code> + <code>Dify AI</code> 充写
          </span>
        </div>
        <div class="ctx-help-item">
          <span class="ctx-help-key">数据源</span>
          <span class="ctx-help-val">
            <code>skills/data/breed_canonical.db</code> · 表 <code>breed_canonical</code><br/>
            当前 <strong>14188 条</strong>映射
          </span>
        </div>
        <div class="ctx-help-item">
          <span class="ctx-help-key">本页能做什么</span>
          <span class="ctx-help-val">
            <strong>查询 + 校准</strong>：品种关键字搜索 · 来源/置信度筛选 · 升降序<br/>
            点 <code>L3</code> 单元格跳到「分类法」页查看该分项详情
          </span>
        </div>
        <div class="ctx-help-item">
          <span class="ctx-help-key">来源标签</span>
          <span class="ctx-help-val">
            <code>etl_v3_sqlite</code> v3 ETL 自动归一（量最大）<br/>
            <code>ai_dify</code> AI — Dify workflow 兜底分配<br/>
            <code>manual</code> 手动 — 人工校准
          </span>
        </div>
      </div>
    </div>
  </Transition>

  <!-- Grid Table (CSS Grid, 列对齐像素级精准) -->
  <div class="ctx-card">
    <div class="grid-scroll" :class="`ctx-density-${density}`">
      <div class="grid-table">
        <!-- Sticky header -->
        <div class="grid-header">
          <div class="grid-head-cell col-breed text-left sortable"
               :class="{ active: sort.col==='breed_clean' }"
               @click="setSort('breed_clean')">
            品种 <span class="sort-icon">{{ sortIcon('breed_clean') }}</span>
          </div>
          <div class="grid-head-cell col-l3 sortable"
               :class="{ active: sort.col==='l3' }"
               @click="setSort('l3')">
            L3 <span class="sort-icon">{{ sortIcon('l3') }}</span>
          </div>
          <div class="grid-head-cell col-l3-name text-left sortable"
               :class="{ active: sort.col==='name_l3' }"
               @click="setSort('name_l3')">
            L3 名称 <span class="sort-icon">{{ sortIcon('name_l3') }}</span>
          </div>
          <div class="grid-head-cell col-source sortable"
               :class="{ active: sort.col==='source' }"
               @click="setSort('source')">
            来源 <span class="sort-icon">{{ sortIcon('source') }}</span>
          </div>
          <div class="grid-head-cell col-confidence sortable"
               :class="{ active: sort.col==='confidence' }"
               @click="setSort('confidence')">
            置信度 <span class="sort-icon">{{ sortIcon('confidence') }}</span>
          </div>
          <div class="grid-head-cell col-updated sortable"
               :class="{ active: sort.col==='updated_at' }"
               @click="setSort('updated_at')">
            更新时间 <span class="sort-icon">{{ sortIcon('updated_at') }}</span>
          </div>
        </div>

        <!-- Body -->
        <div class="grid-body">
          <div v-if="mapLoading" class="grid-row grid-row-empty">
            <div class="grid-cell" style="grid-column: 1 / -1;">加载中...</div>
          </div>
          <div v-else-if="!mapRows.length" class="grid-row grid-row-empty">
            <div class="grid-cell" style="grid-column: 1 / -1;">
              <div class="ctx-empty">
                <div class="ctx-empty-art">🗂️</div>
                <div class="ctx-empty-title">暂无映射条目</div>
                <div class="ctx-empty-hint">试试调整筛选条件或清空全部</div>
                <button class="ctx-btn ctx-btn-cyan" @click="clearMapFilters" style="margin-top:12px">🔍 清空筛选</button>
              </div>
            </div>
          </div>
          <div
            v-for="r in mapRows"
            v-else
            :key="r.breed_clean + (r.l3 || '')"
            class="grid-row"
            :class="rowClass(r)"
            @click="openDrawer(r)"
          >
            <div class="grid-cell col-breed text-left">
              <span class="ctx-breed-text" :title="r.breed_clean">{{ r.breed_clean }}</span>
            </div>
            <div class="grid-cell col-l3">
              <span class="ctx-code-text ctx-l3-code ctx-l3-link"
                    @click.stop="emitJump(r.l3)" :title="`查看 ${r.l3} 详情`">
                {{ r.l3 }} <span class="ctx-l3-arrow">→</span>
              </span>
            </div>
            <div class="grid-cell col-l3-name text-left">
              <div class="ctx-name-stack">
                <span class="ctx-name-l1">{{ r.name_l1 || '—' }}</span>
                <span class="ctx-name-l3">{{ r.name_l3 || '—' }}</span>
              </div>
            </div>
            <div class="grid-cell col-source">
              <span class="ctx-src" :class="`ctx-src-${r.source}`">{{ sourceLabel(r.source) }}</span>
            </div>
            <div class="grid-cell col-confidence">
              <span class="ctx-conf" :class="confClass(r.confidence)">{{ formatConfidence(r.confidence) }}</span>
              <span v-if="r.confidence != null && r.confidence < 1" class="ctx-conf-bar" :style="confBar(r.confidence)"></span>
            </div>
            <div class="grid-cell col-updated ctx-date" :title="r.updated_at">{{ formatDate(r.updated_at) }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <AppPagination
      :current="mapPage"
      :total="mapTotal"
      :page-size="mapPageSize"
      :page-size-options="mapPageSizeOptions"
      show-size-changer
      info-template="第 {from}-{to} 条 / 共 {total} 条"
      @change="loadMap"
      @update:page-size="mapPageSize = $event; loadMap(1)"
    />
  </div>

  <!-- Row Detail Drawer -->
  <div v-if="drawerRow" class="ctx-drawer-mask" @click.self="drawerRow = null">
    <div class="ctx-drawer">
      <div class="ctx-drawer-header">
        <div>
          <div class="ctx-drawer-title">品种映射详情</div>
          <div class="ctx-drawer-sub">
            <span class="ctx-src" :class="`ctx-src-${drawerRow.source}`">{{ sourceLabel(drawerRow.source) }}</span>
            <span class="ctx-drawer-name">{{ truncate(drawerRow.breed_clean, 32) }}</span>
          </div>
        </div>
        <button class="ctx-drawer-close" @click="drawerRow = null">×</button>
      </div>
      <div class="ctx-drawer-body">
        <div class="ctx-drawer-section">
          <div class="ctx-drawer-section-title">分类</div>
          <div class="ctx-drawer-grid">
            <div class="ctx-drawer-field"><label>L3 编码</label><span class="ctx-code-text ctx-l3-code">{{ drawerRow.l3 }}</span></div>
            <div class="ctx-drawer-field"><label>L3 名称</label><span>{{ drawerRow.name_l3 || '—' }}</span></div>
            <div class="ctx-drawer-field ctx-drawer-wide"><label>L1 大类</label><span>{{ drawerRow.name_l1 || '—' }}</span></div>
            <div class="ctx-drawer-field ctx-drawer-wide"><label>L2 分部</label><span>{{ drawerRow.name_l2 || '—' }}</span></div>
          </div>
        </div>
        <div class="ctx-drawer-section">
          <div class="ctx-drawer-section-title">置信度</div>
          <div class="ctx-drawer-grid">
            <div class="ctx-drawer-field"><label>数值</label>
              <span class="ctx-conf" :class="confClass(drawerRow.confidence)">{{ formatConfidence(drawerRow.confidence) }}</span>
            </div>
            <div class="ctx-drawer-field"><label>等级</label>
              <span class="ctx-conf-label" :class="confClass(drawerRow.confidence)">{{ confLabel(drawerRow.confidence) }}</span>
            </div>
            <div class="ctx-drawer-field ctx-drawer-wide"><label>更新时间</label><span>{{ formatDate(drawerRow.updated_at) }}</span></div>
          </div>
        </div>
        <div class="ctx-drawer-actions">
          <button class="ctx-btn ctx-btn-cyan" @click="emitJump(drawerRow.l3); drawerRow = null">→ 查看 L3 分类详情</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import axios from 'axios'
import AppPagination from './AppPagination.vue'

const props = defineProps({
  initialL3Filter: { type: String, default: '' },
  dateFrom: { type: String, default: '' },
  dateTo:   { type: String, default: '' },
})

const emit = defineEmits(['jump-to-breed-map'])
const API = import.meta.env.VITE_API_URL || '/api'

// ── 状态 ──
const showHelp = ref(false)
const drawerRow = ref(null)
const mapKeyword = ref('')
const filterSource = ref('')
const filterConfidence = ref('')
const sourceOpts = ref([])
const mapPageSize = ref(50)
const mapPageSizeOptions = [50, 100, 200]
const mapRows = ref([])
const mapTotal = ref(0)
const mapPage = ref(1)
const mapLoading = ref(false)
const sort = ref({ col: 'confidence', dir: 'desc' })
const density = ref('normal')

// ── 工具 ──
const srcLabels = {
  v1_translated: '翻译',
  ai_v2: 'AI v2',
  manual: '手动',
  etl_v3_sqlite: 'v3 ETL',
  ai_dify: 'AI · Dify',
}
function sourceLabel(s) { return srcLabels[s] || s || '—' }

function confClass(c) {
  if (c == null) return 'ctx-conf-mid'
  if (c >= 0.85) return 'ctx-conf-high'
  if (c >= 0.7) return 'ctx-conf-mid'
  return 'ctx-conf-low'
}
function confLabel(c) {
  if (c == null) return '—'
  if (c >= 0.85) return '高可信'
  if (c >= 0.7) return '需复核'
  return '需重映射'
}
function formatConfidence(c) {
  if (c == null) return '—'
  return c.toFixed(2)
}
function confBar(c) {
  const pct = c == null ? 0 : Math.max(0, Math.min(100, c * 100))
  const color = c >= 0.85 ? 'var(--status-ok)' : c >= 0.7 ? 'var(--status-warn)' : 'var(--status-alert)'
  return { width: `${pct}%`, background: color }
}

function formatDate(s) {
  if (!s) return '—'
  let iso = String(s)
  if (iso.includes(' ') && !iso.includes('T')) iso = iso.replace(' ', 'T') + 'Z'
  if (!iso.endsWith('Z') && !iso.match(/[+-]\d{2}:?\d{2}$/)) iso = iso + 'Z'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return String(s).slice(0, 19).replace('T', ' ')
  const utc = d.getTime()
  const cn = new Date(utc + 8 * 3600 * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${cn.getUTCFullYear()}-${pad(cn.getUTCMonth()+1)}-${pad(cn.getUTCDate())} ${pad(cn.getUTCHours())}:${pad(cn.getUTCMinutes())}`
}

function truncate(s, n) {
  if (!s) return ''
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

function setSort(col) {
  if (sort.value.col === col) {
    sort.value.dir = sort.value.dir === 'asc' ? 'desc' : 'asc'
  } else {
    sort.value.col = col
    sort.value.dir = 'asc'
  }
  loadMap(1)
}
function sortIcon(col) {
  if (sort.value.col !== col) return '↕'
  return sort.value.dir === 'asc' ? '↑' : '↓'
}

const dateActive = computed(() => !!(props.dateFrom || props.dateTo))
const hasFilter = computed(() =>
  !!mapKeyword.value || !!filterSource.value || !!filterConfidence.value
)

function rowClass(r) {
  if (r.confidence != null && r.confidence < 0.7) return 'grid-row-low'
  return ''
}

function openDrawer(r) { drawerRow.value = r }

function debounceLoadMap(p) {
  clearTimeout(window._ctx_map_debounce)
  window._ctx_map_debounce = setTimeout(() => loadMap(p || 1), 300)
}

async function loadMap(p = 1) {
  mapLoading.value = true
  try {
    const params = {
      page: p,
      page_size: mapPageSize.value,
      sort_by: sort.value.col,
      sort_dir: sort.value.dir,
    }
    if (mapKeyword.value.trim()) params.keyword = mapKeyword.value.trim()
    if (filterSource.value) params.source = filterSource.value
    if (filterConfidence.value) {
      if (filterConfidence.value === 'high') params.min_confidence = 0.85
      else if (filterConfidence.value === 'mid') params.min_confidence = 0.7
    }
    if (props.dateFrom) params.date_from = props.dateFrom
    if (props.dateTo)   params.date_to   = props.dateTo

    const { data } = await axios.get(`${API}/stats/category-v2-breed-map`, { params })
    let rows = data.rows || []
    if (filterConfidence.value === 'mid') rows = rows.filter(r => r.confidence >= 0.7 && r.confidence < 0.85)
    else if (filterConfidence.value === 'low') rows = rows.filter(r => r.confidence < 0.7)
    mapRows.value = rows
    mapTotal.value = data.total || 0
    if (data.source_options && !sourceOpts.value.length) sourceOpts.value = data.source_options
    mapPage.value = p
  } catch (e) { console.error(e) }
  finally { mapLoading.value = false }
}

function clearMapFilters() {
  mapKeyword.value = ''
  filterSource.value = ''
  filterConfidence.value = ''
  loadMap(1)
}

function exportCsv() {
  if (!mapRows.value.length) return
  const headers = ['品种', 'L3', 'L1', 'L2', 'L3 名称', '来源', '置信度', '更新时间']
  const rows = mapRows.value.map(r => [
    r.breed_clean,
    r.l3 || '',
    r.name_l1 || '',
    r.name_l2 || '',
    r.name_l3 || '',
    sourceLabel(r.source),
    r.confidence != null ? r.confidence : '',
    formatDate(r.updated_at),
  ])
  const esc = (v) => {
    const s = String(v ?? '')
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
  }
  const csv = '\uFEFF' + [headers, ...rows].map(line => line.map(esc).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `breed-map-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-')}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function onKey(e) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    const el = document.querySelector('.ctx-search-wrap .ctx-input')
    if (el) el.focus()
  }
}

function emitJump(l3) { emit('jump-to-breed-map', l3) }

watch(() => [props.dateFrom, props.dateTo, props.initialL3Filter], () => {
  loadMap(1)
}, { immediate: false })

defineExpose({ loadMap, refresh: () => loadMap(mapPage.value) })

onMounted(() => {
  loadMap(1)
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
})
</script>

<style scoped>
/* Toolbar */
.ctx-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 14px; gap: 12px;
}
.ctx-toolbar-left { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.ctx-toolbar-right { display: flex; gap: 8px; align-items: center; }

.ctx-search-wrap { position: relative; }
.ctx-search-icon {
  position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
  font-size: 13px; pointer-events: none; opacity: 0.8;
}
.ctx-input {
  height: 34px;
  background: var(--surface, #ffffff);
  border: 1px solid var(--surface-3, #e2e8f0);
  border-radius: 8px;
  padding: 0 12px;
  font-size: 13px;
  color: var(--text, #0f172a);
  outline: none;
  font-family: inherit;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}
.ctx-input::placeholder { color: var(--text-3, #94a3b8); }
.ctx-input:hover { border-color: #cbd5e1; }
.ctx-input:focus {
  border-color: var(--primary, #2563eb);
  background: rgba(37,99,235,0.03);
  box-shadow: 0 0 0 3px rgba(37,99,235,0.1);
}
.ctx-search-wrap .ctx-input { padding-left: 32px; width: 240px; }

.ctx-select {
  height: 34px; padding: 0 10px;
  background: var(--surface);
  border: 1px solid var(--surface-3, #e2e8f0);
  border-radius: 8px;
  font-size: 13px; color: var(--text);
  font-family: inherit; cursor: pointer;
  outline: none; transition: border-color 0.15s, box-shadow 0.15s;
}
.ctx-select:hover { border-color: #cbd5e1; }
.ctx-select:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }

.ctx-btn {
  height: 34px; padding: 0 14px; border-radius: 8px; font-size: 13px;
  font-weight: 500; cursor: pointer; border: none; transition: all 0.15s;
  font-family: inherit;
}
.ctx-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ctx-btn-cyan { background: rgba(37,99,235,0.1); color: var(--primary); border: 1px solid rgba(37,99,235,0.2); }
.ctx-btn-cyan:hover { background: rgba(37,99,235,0.2); }
.ctx-btn-ghost { background: transparent; color: var(--text-3); border: 1px solid var(--border); }
.ctx-btn-ghost:hover { background: var(--surface-2); color: var(--text); }

.ctx-date-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px;
  background: rgba(245,158,11,0.1);
  border: 1px solid rgba(245,158,11,0.25);
  color: #b45309;
  border-radius: 6px;
  font-size: 12px;
  font-family: 'Courier New', monospace;
}

/* Card */
.ctx-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; overflow: visible; box-shadow: var(--shadow);
  padding-bottom: 16px;
}
.ctx-card :deep(.pagination) {
  position: sticky;
  bottom: 0;
  background: rgba(255,255,255,0.95);
  backdrop-filter: blur(8px);
  border-radius: 0 0 12px 12px;
  z-index: 5;
}

/* ─────────────────────────────────────────
   CSS Grid 表格 — 列对齐像素级精准（2026-07-15)
   每行/表头都用同一套 grid-template-columns，
   浏览器对每个 row 独立 grid layout，但模板相同 → 列同宽
   ───────────────────────────────────────── */
.grid-scroll {
  overflow-x: auto;
  overflow-y: visible;
  max-height: calc(100vh - 280px);
}

.grid-table {
  /* 仅宽度约束；列定位在子级由 grid-template-columns 定义 */
  width: 100%;
  min-width: 1050px;  /* 6 列最小总宽 — 防止窗口太窄挤压 */
}

/* 6 列定义 — 所有 row/header 共用 */
.grid-table .grid-header,
.grid-table .grid-row {
  display: grid;
  grid-template-columns:
    minmax(220px, 1fr)    /* col-breed       */
    100px                  /* col-l3          */
    minmax(150px, 1fr)    /* col-l3-name     */
    90px                   /* col-source      */
    110px                  /* col-confidence  */
    150px;                 /* col-updated     */
  align-items: stretch;
}

.grid-header {
  position: sticky;
  top: 0;
  z-index: 4;
  background: var(--surface-2, #f8fafc);
  box-shadow: 0 1px 0 var(--border);
}

.grid-head-cell,
.grid-cell {
  display: flex;
  align-items: center;
  padding: 10px 10px;
  border-right: 1px solid var(--border);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--text, #0f172a);
  box-sizing: border-box;
}
.grid-head-cell:last-child,
.grid-cell:last-child { border-right: none; }

.grid-head-cell {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-2);
  text-transform: none;
  letter-spacing: 0;
}
.grid-head-cell.sortable { cursor: pointer; user-select: none; transition: background 0.15s; }
.grid-head-cell.sortable:hover { background: var(--surface-3, #f1f5f9); }
.grid-head-cell.active { color: var(--primary); background: rgba(37,99,235,0.06); }
.grid-head-cell .sort-icon { margin-left: 4px; font-size: 10px; opacity: 0.6; }
.grid-head-cell.active .sort-icon { opacity: 1; }

/* 对齐 */
.col-breed, .col-l3-name { justify-content: flex-start; }
.col-l3, .col-source, .col-confidence, .col-updated { justify-content: center; }
.text-left { justify-content: flex-start !important; text-align: left; }

.col-l3-name { white-space: normal; }  /* 名称两行可换行 */
.col-breed { white-space: nowrap; }

/* 行交互 */
.grid-row {
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.1s;
  background: var(--surface);
}
.grid-row:last-child { border-bottom: none; }
.grid-row:hover { background: rgba(37,99,235,0.04); }
.grid-row.grid-row-low { background: rgba(239,68,68,0.05); }
.grid-row.grid-row-low:hover { background: rgba(239,68,68,0.1); }
/* zebra */
.grid-row:nth-child(even) { background: var(--surface-2, #f8fafc); }
.grid-row:nth-child(even):hover { background: rgba(37,99,235,0.06); }
.grid-row.grid-row-low:nth-child(even) { background: rgba(239,68,68,0.08); }

.grid-row-empty {
  cursor: default;
  background: var(--surface) !important;
}
.grid-row-empty:hover { background: var(--surface) !important; }
.ctx-empty { text-align: center; color: var(--text-2, #475569); padding: 48px 36px; width: 100%; }
.ctx-empty-art { font-size: 48px; opacity: 0.6; margin-bottom: 12px; }
.ctx-empty-title { font-size: 14px; font-weight: 600; color: var(--text, #0f172a); margin-bottom: 6px; }
.ctx-empty-hint { font-size: 12px; color: var(--text-3, #94a3b8); }

/* Density */
.ctx-density-compact .grid-row { min-height: 36px; }
.ctx-density-compact .grid-head-cell,
.ctx-density-compact .grid-cell { padding: 4px 10px; font-size: 12px; }
.ctx-density-normal .grid-row { min-height: 56px; }
.ctx-density-loose .grid-row { min-height: 72px; }
.ctx-density-loose .grid-head-cell,
.ctx-density-loose .grid-cell { padding: 14px 10px; }

/* Density toggle */
.ctx-density-toggle {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  height: 34px;
}
.ctx-density-toggle button {
  padding: 0 12px;
  background: transparent;
  border: none;
  color: var(--text-3);
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
  font-weight: 500;
  transition: all 0.15s;
}
.ctx-density-toggle button + button { border-left: 1px solid var(--border); }
.ctx-density-toggle button:hover { background: var(--surface-2); color: var(--text); }
.ctx-density-toggle button.active { background: var(--primary); color: white; }

/* Help */
.ctx-help {
  background: linear-gradient(135deg, rgba(37,99,235,0.04), rgba(37,99,235,0.01));
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 10px;
  padding: 16px 18px;
  margin-bottom: 16px;
}
.ctx-help-title { font-size: 13px; font-weight: 700; color: var(--primary); margin-bottom: 14px; }
.ctx-help-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 10px 24px;
}
.ctx-help-item { display: flex; gap: 10px; font-size: 11.5px; line-height: 1.7; }
.ctx-help-key { color: var(--primary); font-weight: 600; white-space: nowrap; min-width: 80px; }
.ctx-help-val { color: var(--text-3); }
.ctx-help-val code {
  font-family: 'Courier New', monospace; font-size: 11px;
  color: var(--primary); background: rgba(37,99,235,0.08);
  border-radius: 3px; padding: 1px 4px; font-weight: 500;
}
.ctx-help-val strong { color: var(--text, #0f172a); font-weight: 600; }

.ctx-slide-enter-active, .ctx-slide-leave-active { transition: all 0.2s ease; overflow: hidden; }
.ctx-slide-enter-from, .ctx-slide-leave-to { opacity: 0; transform: translateY(-6px); }

/* Drawer (unchanged) */
.ctx-drawer-mask {
  position: fixed; inset: 0; background: rgba(15,23,42,0.25);
  display: flex; justify-content: flex-end; z-index: 9999;
  backdrop-filter: blur(2px);
}
.ctx-drawer {
  width: 460px; max-width: 90vw; height: 100vh;
  background: var(--surface); border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  box-shadow: -8px 0 24px rgba(15,23,42,0.08);
  animation: ctxDrawerIn 0.22s ease;
}
@keyframes ctxDrawerIn {
  from { transform: translateX(40px); opacity: 0; }
  to   { transform: translateX(0); opacity: 1; }
}
.ctx-drawer-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 20px 24px; border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(37,99,235,0.04), transparent);
}
.ctx-drawer-title { font-size: 13px; font-weight: 700; color: var(--primary); margin-bottom: 8px; }
.ctx-drawer-sub { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ctx-drawer-name { font-size: 14px; font-weight: 600; color: var(--text, #0f172a); }
.ctx-drawer-close {
  width: 28px; height: 28px; border-radius: 6px;
  background: transparent; border: 1px solid var(--border);
  color: var(--text-2); font-size: 18px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.ctx-drawer-close:hover { background: var(--surface-2); color: var(--text); }
.ctx-drawer-body { flex: 1; overflow-y: auto; padding: 16px 24px 24px; }
.ctx-drawer-section { margin-bottom: 20px; }
.ctx-drawer-section-title {
  font-size: 11px; font-weight: 700; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.05em;
  margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px dashed var(--border);
}
.ctx-drawer-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; }
.ctx-drawer-field { display: flex; flex-direction: column; gap: 2px; }
.ctx-drawer-field.ctx-drawer-wide { grid-column: 1 / -1; }
.ctx-drawer-field label { font-size: 11px; color: var(--text-3); font-weight: 600; }
.ctx-drawer-field span { font-size: 13px; color: var(--text, #0f172a); font-weight: 500; }
.ctx-drawer-actions { padding-top: 8px; border-top: 1px solid var(--border); }

/* Breed-map specific text styles */
.ctx-breed-text { color: #1e293b; font-weight: 600; font-size: 13px; }
.ctx-code-text {
  font-family: 'Courier New', monospace; font-size: 12px;
  color: var(--text-2);
}
.ctx-l3-code { color: var(--primary); font-weight: 600; }
.ctx-l3-link { cursor: pointer; transition: color 0.15s; }
.ctx-l3-link:hover { color: var(--primary-dark, #1d4ed8); text-decoration: underline; }
.ctx-l3-arrow { opacity: 0.4; font-size: 11px; transition: all 0.15s; }
.ctx-l3-link:hover .ctx-l3-arrow { opacity: 1; transform: translateX(2px); }
.ctx-name-stack { display: flex; flex-direction: column; gap: 2px; }
.ctx-name-l1 { font-size: 11px; color: var(--text-3); font-family: 'Courier New', monospace; line-height: 1.3; }
.ctx-name-l3 { font-size: 13px; font-weight: 600; color: #1e293b; line-height: 1.3; }
.ctx-src {
  display: inline-block; padding: 2px 9px; border-radius: 5px;
  font-size: 11px; font-weight: 600;
}
.ctx-src-v1_translated { background: rgba(37,99,235,0.1); color: var(--primary); }
.ctx-src-ai_v2 { background: rgba(251,191,36,0.1); color: var(--status-warn); }
.ctx-src-manual { background: rgba(52,211,153,0.1); color: var(--status-ok); }
.ctx-src-etl_v3_sqlite { background: rgba(99,102,241,0.12); color: #6366f1; }
.ctx-src-ai_dify { background: rgba(168,85,247,0.12); color: #a855f7; }
.ctx-conf { font-weight: 700; font-size: 12px; font-family: 'Courier New', monospace; }
.ctx-conf-label { font-weight: 600; font-size: 12px; }
.ctx-conf-high { color: var(--status-ok); }
.ctx-conf-mid  { color: var(--status-warn); }
.ctx-conf-low  { color: var(--status-alert); }
.ctx-conf-bar {
  display: inline-block; height: 4px; border-radius: 2px;
  margin-left: 6px; vertical-align: middle;
  min-width: 24px; max-width: 60px; opacity: 0.65;
}
.ctx-date { color: var(--text-3); font-size: 12px; white-space: nowrap; font-family: 'Courier New', monospace; justify-content: flex-start !important; }
</style>
