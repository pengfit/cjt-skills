<template>
  <!-- Toolbar -->
  <div class="ctx-toolbar">
    <div class="ctx-toolbar-main">
      <input class="ctx-input" v-model="search" placeholder="🔍 搜索 breed_clean / normalized_breed / note..." @input="debounceReload(1)" />
      <button v-if="search" class="canon-clear-btn" @click="clearAllFilters" title="清除搜索">×</button>
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
        <div class="canon-help-row"><b>是什么</b>存储于 <code>skills/data/breed_canonical.db</code> · 表 <code>breed_canonical</code> 的品种→L3 映射 + normalized_breed（多对一合并名）。</div>
        <div class="canon-help-row"><b>怎么检索</b>关键字（breed_clean / normalized_breed / note）模糊匹配 + source / l3_code 精确过滤 + NULL l3 单独筛选。</div>
        <div class="canon-help-row"><b>source 含义</b><code>ai_dify</code> DWS→NORM Dify 自动写入 · 写入路径唯一（build_norm_index.py:375）</div>
        <div class="canon-help-row"><b>confidence</b>≥0.95 高 · 0.85–0.95 中 · 0.5–0.85 低 · &lt;0.5 不可信</div>
        <div class="canon-help-row"><b>normalized_breed</b>NORM 跨城 join 用的归一化名，多对一合并（多 raw 映射到同一标准名）。</div>
      </div>
    </div>
  </Transition>

  <!-- 2026-07-28:Phase 2 — 自研 CSS Grid 表格改 Element Plus <el-table> -->
  <div class="canon-table-wrap">
    <el-table
      v-loading="loading"
      :data="rows"
      stripe
      class="canon-el-table"
      empty-text="暂无映射"
      :row-key="(r) => r.breed_clean"
      @row-click="openDrawer"
    >
      <el-table-column type="index" :index="(i) => (page - 1) * size + i + 1" label="#" width="60" align="center" />
      <el-table-column prop="breed_clean" label="breed_clean" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="canon-cell-strong">{{ row.breed_clean }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="normalized_breed" label="normalized_breed" min-width="180" show-overflow-tooltip />
      <el-table-column label="source" width="120" align="center">
        <template #default="{ row }">
          <span class="canon-source-tag">{{ row.source }}</span>
        </template>
      </el-table-column>
      <el-table-column label="confidence" width="110" align="center">
        <template #default="{ row }">
          <span class="canon-conf" :class="confClass(row.confidence)">{{ row.confidence.toFixed(2) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="note" label="note" min-width="200" show-overflow-tooltip />
      <el-table-column label="updated_at" width="180">
        <template #default="{ row }">
          {{ row.updated_at ? row.updated_at.slice(0, 19) : '—' }}
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 (Phase 2:保留 vec-pagination 全局 .page-btn 样式,见 style.css 行 1104+) -->
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

  <!-- 2026-07-28:Phase 2 — 自研 mask+div 抽屉改 Element Plus <el-drawer> -->
  <el-drawer
    v-model="drawerVisible"
    direction="rtl"
    size="460px"
    :with-header="false"
  >
    <div v-if="drawerRow" class="ctx-drawer">
      <div class="ctx-drawer-header">
        <div>
          <div class="ctx-drawer-title">品种归一详情</div>
          <div class="ctx-drawer-sub">
            <span class="canon-source-tag">{{ drawerRow.source }}</span>
            <span class="ctx-drawer-name">{{ drawerRow.breed_clean }}</span>
          </div>
        </div>
        <button class="ctx-drawer-close" @click="drawerVisible = false">×</button>
      </div>
      <div class="ctx-drawer-body">
        <div class="ctx-drawer-section">
          <div class="ctx-drawer-section-title">映射</div>
          <div class="ctx-drawer-grid">
            <div class="ctx-drawer-field ctx-drawer-wide"><label>breed_clean</label><span class="canon-cell-strong">{{ drawerRow.breed_clean }}</span></div>
            <div class="ctx-drawer-field ctx-drawer-wide"><label>normalized_breed</label><span>{{ drawerRow.normalized_breed }}</span></div>
            <div class="ctx-drawer-field"><label>source</label><span class="canon-source-tag">{{ drawerRow.source }}</span></div>
            <div class="ctx-drawer-field"><label>confidence</label><span class="canon-conf" :class="confClass(drawerRow.confidence)">{{ drawerRow.confidence.toFixed(2) }}</span></div>
            <div class="ctx-drawer-field"><label>created_at</label><span class="canon-time">{{ drawerRow.created_at || '—' }}</span></div>
            <div class="ctx-drawer-field"><label>updated_at</label><span class="canon-time">{{ drawerRow.updated_at || '—' }}</span></div>
            <div class="ctx-drawer-field ctx-drawer-wide"><label>note</label><span class="canon-note">{{ drawerRow.note || '—' }}</span></div>
          </div>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

// 8 列 (id / breed / norm / l3 / source / conf / note / date)
const GRID_COLS = '52px minmax(180px, 1.2fr) minmax(180px, 1fr) minmax(110px, 1fr) minmax(110px, 1fr) minmax(200px, 1.5fr) minmax(150px, 1fr)'

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
// 2026-07-28:Phase 2 — el-drawer v-model 用 boolean
const drawerVisible = ref(false)

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

function clearAllFilters() {
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

function openDrawer(r) {
  drawerRow.value = r
  drawerVisible.value = true
}

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
  try {
    const r = await fetch('/api/canon/breeds?' + params)
    if (!r.ok) { rows.value = []; total.value = 0; pages.value = 0; return }
    const d = await r.json()
    rows.value = d.rows || []
    total.value = d.total || 0
    pages.value = Math.ceil(total.value / size.value) || 1
    jumpPage.value = page.value
  } catch (e) { console.error('[canon] list load failed', e) }
  finally { loading.value = false }
}

onMounted(() => { loadStats(); reload(1) })
</script>

<style scoped>
/* 2026-07-28 Phase 2 cleanup:
   表格迁 <el-table> / 抽屉迁 <el-drawer> / 加载态走 el-table v-loading。
   已删除: .canon-loading / .canon-spinner / .canon-table / .canon-row / .canon-row-head / 
            .canon-row-data / .canon-cell / .text-left / .col-id / .col-breed / .col-norm /
            .col-note / .col-date / .canon-empty* / .ctx-drawer-mask / .canon-toggle / .ctx-select 等。
   保留: .ctx-toolbar / .ctx-input / .canon-help* / .canon-el-table 容器 / 
         .canon-source-tag / .canon-conf* / .ctx-drawer* / .canon-pagination / @keyframes 等。 */

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

/* ── Help ── */
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

/* ── Table 容器(el-table 外壳) ── */
.canon-table-wrap {
  background: var(--surface, #fff);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
  overflow: auto;
  max-height: calc(100vh - 420px);
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}

/* el-table 列内容排版 */
.canon-cell-strong { font-weight: 600; color: #111827; }

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

/* ── Drawer (el-drawer 内部内容容器) ── */
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
.ctx-drawer-field.ctx-drawer-wide { grid-column: 1 / -1; }
.ctx-drawer-field label { font-size: 11px; color: var(--text-3); font-weight: 600; }
.ctx-drawer-field span { font-size: 13px; color: var(--text, #1e293b); font-weight: 500; }
.canon-time { font-family: 'Courier New', monospace; font-size: 12px; }
.canon-note { color: var(--text-2); font-size: 12px; }

/* ── Pagination(沿用全局 .page-btn) ── */
.canon-pagination {
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

/* ── Slide down ── */
.slide-down-enter-active, .slide-down-leave-active { transition: all 0.2s ease; }
.slide-down-enter-from, .slide-down-leave-to { opacity: 0; transform: translateY(-6px); }

/* ── Mobile ── */
@media (max-width: 768px) {
  .canon-pagination { flex-direction: column; align-items: stretch; }
  .ctx-drawer { width: 92vw !important; max-width: 360px !important; }
}
</style>