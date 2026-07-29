<template>
  <!-- Toolbar(2026-07-29 彻底统一:与 /taxonomy 同款 .ctx-search-wrap,删 chips / 📖 / × 输入清空按钮) -->
  <div class="ctx-toolbar">
    <div class="ctx-search-wrap">
      <span class="ctx-search-icon">🔍</span>
      <input
        class="ctx-input"
        v-model="search"
        placeholder="搜索 breed_clean / normalized_breed / note..."
        @input="debounceReload(1)"
      />
    </div>
  </div>

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

    <!-- 分页(2026-07-29 彻底统一:换 <AppPagination> 与 /taxonomy 一致;pageSize 默认 20,options [20,50,100]) -->
    <AppPagination
      :current="page"
      :total="total"
      :page-size="size"
      :page-size-options="pageSizeOptions"
      show-size-changer
      info-template="第 {from}-{to} 条 / 共 {total} 条"
      @change="reload"
      @update:page-size="size = $event; reload(1)"
    />
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
import { ref, onMounted } from 'vue'
import AppPagination from './AppPagination.vue'

const search = ref('')
const page = ref(1)
const size = ref(20)
const pageSizeOptions = [20, 50, 100]
const total = ref(0)
const rows = ref([])
const stats = ref(null)
const loading = ref(false)
const drawerRow = ref(null)
// 2026-07-28:Phase 2 — el-drawer v-model 用 boolean
const drawerVisible = ref(false)

function confClass(c) {
  if (c >= 0.95) return 'high'
  if (c >= 0.85) return 'mid'
  if (c >= 0.5) return 'low'
  return 'bad'
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
    if (!r.ok) { rows.value = []; total.value = 0; return }
    const d = await r.json()
    rows.value = d.rows || []
    total.value = d.total || 0
  } catch (e) { console.error('[canon] list load failed', e) }
  finally { loading.value = false }
}

onMounted(() => { loadStats(); reload(1) })
</script>

<style scoped>
/* 2026-07-29 彻底统一(与 /taxonomy 一致):
   删: .ctx-toolbar-main / .ctx-toolbar-side / .canon-clear-btn* / .canon-help-btn* /
       .canon-help* (5 block) / .slide-down-* / .canon-pagination / .page-btn* / .page-jump* / .page-size*。
   .ctx-toolbar 改成 /taxonomy 裸版(无 padding/bg/border-radius,只保留 flex+margin-bottom) — 4 页彻底统一。
   保留: .canon-table-wrap / .canon-cell-strong / .canon-conf* / .canon-source-tag / .canon-time /
         .canon-note / .ctx-input / .ctx-search-wrap / .ctx-search-icon / .ctx-drawer* / @keyframes 等。 */

/* ── Toolbar(与 /taxonomy 同款,仅留搜索) ── */
.ctx-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 14px; gap: 12px;
}
.ctx-search-wrap { position: relative; }
.ctx-search-icon {
  position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
  font-size: 13px; pointer-events: none; opacity: 0.8;
}
.ctx-input {
  background: var(--surface, #ffffff);
  border: 1px solid var(--surface-3, #e2e8f0);
  border-radius: 8px;
  padding: 0 12px;
  font-size: 13px;
  color: var(--text, #0f172a);
  outline: none;
  font-family: inherit;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
  height: 36px;
}
.ctx-input::placeholder { color: var(--text-3, #94a3b8); }
.ctx-input:hover { border-color: #cbd5e1; }
.ctx-input:focus {
  border-color: var(--primary, #2563eb);
  background: rgba(37,99,235,0.03);
  box-shadow: 0 0 0 3px rgba(37,99,235,0.1);
}
.ctx-search-wrap .ctx-input { padding-left: 32px; width: 240px; }

/* ── Table 容器(el-table 外壳) ── */
.canon-table-wrap {
  background: var(--surface, #fff);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
  /* 2026-07-29 跟 /taxonomy 对齐:去掉 max-height + overflow:auto,
     让 el-table 自然增长,溢出由 el-main 的 overflow-y:auto 接住 */
  overflow: visible;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.canon-table-wrap :deep(.pagination) {
  position: sticky;
  bottom: 0;
  background: rgba(255,255,255,0.95);
  backdrop-filter: blur(8px);
  border-top: 1px solid rgba(15,23,42,0.06);
  border-radius: 0 0 10px 10px;
  padding: 12px 18px;
  z-index: 5;
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

/* ── Mobile ── */
@media (max-width: 768px) {
  .ctx-drawer { width: 92vw !important; max-width: 360px !important; }
}
</style>