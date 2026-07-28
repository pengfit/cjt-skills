<template>
  <!-- Toolbar -->
  <div class="ctx-toolbar">
    <div class="ctx-toolbar-main">
      <input class="ctx-input" v-model="search" placeholder="🔍 搜索 breed_clean..." @input="debounceReload(1)" />
      <button v-if="search" class="canon-clear-btn" @click="clearFilters" title="清除搜索">×</button>
    </div>
    <div class="ctx-toolbar-side">
      <button class="canon-help-btn" :class="{ active: showHelp }" @click="showHelp = !showHelp">
        {{ showHelp ? '🔼 收起说明' : '📖 使用说明' }}
      </button>
    </div>
  </div>

  <!-- 帮助 -->
  <Transition name="slide-down">
    <div class="canon-help" v-if="showHelp">
      <div class="canon-help-grid">
        <div class="canon-help-row"><b>是什么</b>存储于 <code>skills/data/category_v3_rules.db</code> · 表 <code>breed_l3_map_v3</code> 的品种→L3 映射表，由 DWD→DWS ETL 第二轮 Dify 兜底自动写入。</div>
        <div class="canon-help-row"><b>怎么检索</b>关键字（breed_clean）模糊匹配 + source 精确过滤 + l3 精确过滤 + confidence 阈值过滤。</div>
        <div class="canon-help-row"><b>source 含义</b><code>ai_v3</code> DWD→DWS 第二轮 Dify 自动写入 · <code>manual_*</code> 人工修正 · <code>ai_v2</code> 旧 v2 字典继承</div>
        <div class="canon-help-row"><b>confidence</b>≥0.95 高 · 0.85–0.95 中 · 0.5–0.85 低 · &lt;0.5 不可信</div>
        <div class="canon-help-row"><b>写入路径</b>本页只读。写入由 DWD→DWS ETL（<code>classify_v3_batch</code>，ai/service.py:833）负责。</div>
      </div>
    </div>
  </Transition>

  <!-- Main table (CSS Grid) -->
  <div class="canon-table-wrap">
    <div v-if="loading" class="canon-loading">
      <div class="canon-spinner"></div>
      <span>加载中…</span>
    </div>

    <div v-else class="canon-table" :style="{ gridTemplateColumns: GRID_COLS }">
      <div class="canon-row canon-row-head">
        <div class="canon-cell col-id">#</div>
        <div class="canon-cell col-breed text-left">breed_clean</div>
        <div class="canon-cell col-l3">l3</div>
        <div class="canon-cell col-source">source</div>
        <div class="canon-cell col-conf">confidence</div>
        <div class="canon-cell col-date">updated_at</div>
      </div>

      <div v-for="(r, idx) in rows" :key="r.breed_clean" class="canon-row canon-row-data" @click="openDrawer(r)">
        <div class="canon-cell col-id">{{ (page - 1) * size + idx + 1 }}</div>
        <div class="canon-cell col-breed text-left canon-cell-strong" :title="r.breed_clean">{{ r.breed_clean }}</div>
        <div class="canon-cell col-l3">
          <span v-if="r.l3" class="canon-l3-pill">{{ r.l3 }}</span>
          <span v-else class="canon-l3-pill canon-l3-pill-warn">UNCLASSIFIED</span>
        </div>
        <div class="canon-cell col-source">
          <span class="canon-source-tag">{{ r.source }}</span>
        </div>
        <div class="canon-cell col-conf">
          <span class="canon-conf" :class="confClass(r.confidence)">{{ r.confidence.toFixed(2) }}</span>
        </div>
        <div class="canon-cell col-date">{{ r.updated_at ? r.updated_at.slice(0, 19) : '—' }}</div>
      </div>

      <div v-if="!loading && !rows.length" class="canon-empty">
        <div class="canon-empty-icon">📭</div>
        <div class="canon-empty-title">{{ hasFilter ? '没有匹配当前筛选的映射' : '暂无映射' }}</div>
        <div class="canon-empty-hint">{{ hasFilter ? '点击【全部清除】或单独移除筛选条件' : 'check category_v3_rules.db 是否存在 / 是否有数据' }}</div>
      </div>
    </div>
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

  <!-- Row detail drawer -->
  <div v-if="drawerRow" class="ctx-drawer-mask" @click.self="drawerRow = null">
    <div class="ctx-drawer">
      <div class="ctx-drawer-header">
        <div>
          <div class="ctx-drawer-title">品种映射详情</div>
          <div class="ctx-drawer-sub">
            <span class="canon-source-tag">{{ drawerRow.source }}</span>
            <span class="ctx-drawer-name">{{ drawerRow.breed_clean }}</span>
          </div>
        </div>
        <button class="ctx-drawer-close" @click="drawerRow = null">×</button>
      </div>
      <div class="ctx-drawer-body">
        <div class="ctx-drawer-section">
          <div class="ctx-drawer-section-title">映射</div>
          <div class="ctx-drawer-grid">
            <div class="ctx-drawer-field"><label>breed_clean</label><span class="canon-cell-strong">{{ drawerRow.breed_clean }}</span></div>
            <div class="ctx-drawer-field"><label>l3 编码</label><span class="canon-l3-pill">{{ drawerRow.l3 || 'UNCLASSIFIED' }}</span></div>
            <div class="ctx-drawer-field"><label>source</label><span class="canon-source-tag">{{ drawerRow.source }}</span></div>
            <div class="ctx-drawer-field"><label>confidence</label><span class="canon-conf" :class="confClass(drawerRow.confidence)">{{ drawerRow.confidence.toFixed(2) }}</span></div>
            <div class="ctx-drawer-field"><label>created_at</label><span class="canon-time">{{ drawerRow.created_at || '—' }}</span></div>
            <div class="ctx-drawer-field"><label>updated_at</label><span class="canon-time">{{ drawerRow.updated_at || '—' }}</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

// 6 列 (id / breed / l3 / source / conf / date)
const GRID_COLS = '52px minmax(220px, 1.5fr) minmax(110px, 1fr) minmax(140px, 1.2fr) minmax(110px, 1fr) minmax(150px, 1fr)'

const search = ref('')
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
const drawerRow = ref(null)

function confClass(c) {
  if (c >= 0.95) return 'high'
  if (c >= 0.85) return 'mid'
  if (c >= 0.5) return 'low'
  return 'bad'
}

const activeChips = computed(() => {
  const chips = []
  if (search.value.trim()) chips.push({ key: 'search', label: `🔍 「${search.value.trim()}」` })
  return chips
})

const hasFilter = computed(() => activeChips.value.length > 0)

function clearOne(chip) {
  if (chip.key === 'search') search.value = ''
  reload(1)
}

function clearFilters() {
  search.value = ''
  reload(1)
}

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

function openDrawer(r) { drawerRow.value = r }

let debounceTimer = null
function debounceReload(p) {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => reload(p || 1), 300)
}

async function loadStats() {
  try {
    const r = await fetch('/api/stats/breed-l3-map/stats')
    if (r.ok) stats.value = await r.json()
  } catch (e) { console.error('[breed-l3-map] stats load failed', e) }
}

async function reload(p) {
  if (p) page.value = p
  loading.value = true
  const params = new URLSearchParams({ page: page.value, size: size.value })
  if (search.value.trim()) params.set('search', search.value.trim())
  try {
    const r = await fetch('/api/stats/breed-l3-map?' + params)
    if (!r.ok) { rows.value = []; total.value = 0; pages.value = 0; return }
    const d = await r.json()
    rows.value = d.rows || []
    total.value = d.total || 0
    pages.value = Math.ceil(total.value / size.value) || 1
    jumpPage.value = page.value
  } catch (e) { console.error('[breed-l3-map] list load failed', e) }
  finally { loading.value = false }
}

onMounted(() => { loadStats(); reload(1) })
</script>

<style scoped>
/* ── Toolbar ── */
.ctx-toolbar {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px; margin-bottom: 12px;
  background: var(--surface-2, #f8fafc);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
}
.ctx-toolbar-main {
  display: flex; align-items: center; gap: 8px;
  flex: 1; min-width: 0;
  overflow-x: auto; scrollbar-width: thin;
}
.ctx-toolbar-main::-webkit-scrollbar { height: 6px; }
.ctx-toolbar-main::-webkit-scrollbar-thumb { background: rgba(15,23,42,0.18); border-radius: 3px; }
.ctx-toolbar-side {
  display: flex; align-items: center; gap: 8px; flex-shrink: 0;
}
.ctx-input {
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
.ctx-input:focus { border-color: var(--primary, #2563eb); box-shadow: 0 0 0 3px rgba(37,99,235,0.2); }
.ctx-toolbar-main > .ctx-input:not(.ctx-select) { flex: 1 1 200px; max-width: 360px; min-width: 160px; }
.ctx-select { cursor: pointer; min-width: 130px; }
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

/* ── Help panel ── */
.canon-help {
  background: var(--surface-2, #f8fafc);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
  padding: 14px 16px; margin-bottom: 12px;
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

/* ── Main table (CSS Grid) ── */
.canon-table-wrap {
  background: var(--surface, #fff);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
  overflow: auto;
  max-height: calc(100vh - 420px);
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
  min-width: 1100px;
}
.canon-row { display: contents; }
.canon-row-head .canon-cell {
  font-size: 11px; font-weight: 600;
  color: var(--text-3, #6b7280);
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

.col-date { color: var(--text-3); font-size: 11px; font-family: 'Courier New', monospace; }

.canon-empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-3);
  grid-column: 1 / -1;
}
.canon-empty-icon { font-size: 48px; margin-bottom: 12px; opacity: 0.6; }
.canon-empty-title { font-size: 14px; font-weight: 600; color: var(--text-2); margin-bottom: 6px; }
.canon-empty-hint { font-size: 12px; color: var(--text-3); max-width: 480px; margin: 0 auto; }

/* ── Drawer ── */
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
@keyframes ctxDrawerIn { from { transform: translateX(40px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
.ctx-drawer-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 20px 24px; border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(37,99,235,0.04), transparent);
}
.ctx-drawer-title { font-size: 13px; font-weight: 700; color: var(--primary); margin-bottom: 8px; }
.ctx-drawer-sub { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ctx-drawer-name { font-size: 14px; font-weight: 600; color: var(--text, #1e293b); }
.ctx-drawer-close {
  width: 28px; height: 28px; border-radius: 6px;
  background: transparent; border: 1px solid var(--border);
  color: var(--text-2); font-size: 18px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
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
.ctx-drawer-field label { font-size: 11px; color: var(--text-3); font-weight: 600; }
.ctx-drawer-field span { font-size: 13px; color: var(--text, #1e293b); font-weight: 500; }
.canon-time { font-family: 'Courier New', monospace; font-size: 12px; }

/* ── Pagination ── */
.canon-pagination {
  position: sticky; bottom: 0;
  display: flex; align-items: center; justify-content: center;
  gap: 8px; padding: 12px 18px; margin-top: 12px;
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

/* ── Slide down ── */
.slide-down-enter-active, .slide-down-leave-active { transition: all 0.2s ease; }
.slide-down-enter-from, .slide-down-leave-to { opacity: 0; transform: translateY(-6px); }

/* ── Mobile ── */
@media (max-width: 768px) {
  .canon-pagination { flex-direction: column; align-items: stretch; }
  .ctx-drawer { width: 92vw !important; max-width: 360px !important; }
}
</style>