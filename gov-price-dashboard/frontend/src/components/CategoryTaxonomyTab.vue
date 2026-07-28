<template>
  <!-- Toolbar -->
  <div class="ctx-toolbar">
    <div class="ctx-search-wrap">
      <span class="ctx-search-icon">🔍</span>
      <input
        class="ctx-input"
        v-model="taxKeyword"
        placeholder="搜索名称 / 编码 / GB50500 / IFC..."
        @input="debounceLoadTaxonomy(1)"
      />
    </div>
    <div class="ctx-toolbar-right">
      <button class="ctx-btn ctx-btn-cyan" @click="showHelp = !showHelp">
        {{ showHelp ? '🔼 收起' : '📖 使用说明' }}
      </button>
    </div>
  </div>

  <div class="ctx-filter-chips" v-if="taxKeyword">
    <span class="ctx-chip">
      搜索: "{{ taxKeyword }}"
      <button class="ctx-chip-x" @click="taxKeyword=''; debounceLoadTaxonomy(1)" title="移除">×</button>
    </span>
  </div>

  <!-- 使用说明 -->
  <Transition name="ctx-slide">
    <div class="ctx-help" v-if="showHelp">
      <div class="ctx-help-title">📖 分类体系说明</div>
      <div class="ctx-help-grid">
        <div class="ctx-help-item">
          <span class="ctx-help-key">是什么</span>
          <span class="ctx-help-val">
            3 级分类法（<code>L1</code> 大类 / <code>L2</code> 分部 / <code>L3</code> 分项）<br/>
            附 <strong>GB50500</strong> 国标编码 · <strong>IFC</strong> BIM 分类 · <strong>Uniclass</strong> 代码
          </span>
        </div>
        <div class="ctx-help-item">
          <span class="ctx-help-key">数据源</span>
          <span class="ctx-help-val">
            分类骨架读 <code>skills/data/category_v3_rules.db</code> · 表 <code>category_v3</code><br/>
            （DWD→DWS ETL live 写入，不依赖 breed_canonical.db 快照）<br/>
            <strong>9 L1</strong> 大类 · <strong>57 L2</strong> 分部 · <strong>191 L3</strong> 分项
          </span>
        </div>
        <div class="ctx-help-item">
          <span class="ctx-help-key">本页能做什么</span>
          <span class="ctx-help-val">
            <strong>只读查询</strong>：名称/编码/IFC 搜索 · 升降序 · 分页<br/>
            点 <code>L3</code> 单元格跳到「品种映射」页并定位关联品种
          </span>
        </div>
      </div>
    </div>
  </Transition>

  <!-- 2026-07-28:Phase 2 — 自研 CSS Grid 改 Element Plus <el-table> + <el-table-column> -->
  <div class="ctx-card">
    <el-table
      v-loading="taxLoading"
      :data="taxRows"
      stripe
      class="taxonomy-el-table"
      empty-text="暂无分类条目"
      :row-key="(r) => `${r.l1}-${r.l2}-${r.l3}`"
      @row-click="openDrawer"
      @sort-change="onTaxSortChange"
      :default-sort="taxDefaultSort"
    >
      <el-table-column prop="l1" label="L1" width="60" sortable="custom" align="center">
        <template #default="{ row }">
          <span class="ctx-l1-tag" :class="`ctx-l1-${row.l1}`">{{ row.l1 }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="l2" label="L2" width="80" sortable="custom" align="center">
        <template #default="{ row }">
          <span class="ctx-code-text">{{ row.l2 }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="l3" label="L3" width="100" sortable="custom" align="center">
        <template #default="{ row }">
          <span class="ctx-code-text ctx-l3-code ctx-l3-link" @click.stop="emitJump(row.l3)" :title="`查看 ${row.l3} 关联品种`">
            {{ row.l3 }} <span class="ctx-l3-arrow">→</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="gb_50500" label="GB50500" width="110" align="center">
        <template #default="{ row }">
          <span class="ctx-code-text ctx-gb">{{ row.gb_50500 || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="standard_name" label="国标" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="ctx-std-name">{{ row.standard_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="name_l3" label="分类名称" min-width="180" sortable="custom" show-overflow-tooltip>
        <template #default="{ row }">
          <div class="ctx-name-stack">
            <span class="ctx-name-l1">› {{ row.name_l1 || '—' }}</span>
            <span class="ctx-name-l3">{{ row.name_l3 || row.name_l2 || row.l3 }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="eng_part" label="工程部位" width="100" align="center">
        <template #default="{ row }">
          <span class="ctx-tag" :class="`ctx-tag-part-${row.eng_part}`">{{ row.eng_part || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="main_or_aux" label="主辅材" width="80" align="center">
        <template #default="{ row }">
          <span class="ctx-main-aux" :class="`ctx-ma-${row.main_or_aux}`">{{ row.main_or_aux || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="unit" label="单位" width="80" align="center">
        <template #default="{ row }">
          <span class="ctx-unit">{{ row.unit || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="ifc_class" label="IFC" min-width="140" show-overflow-tooltip />
      <el-table-column prop="uniclass_ss" label="Uniclass" min-width="140" show-overflow-tooltip />
    </el-table>

    <AppPagination
      :current="taxPage"
      :total="taxTotal"
      :page-size="taxPageSize"
      :page-size-options="taxPageSizeOptions"
      show-size-changer
      info-template="第 {from}-{to} 条 / 共 {total} 条"
      @change="loadTaxonomy"
      @update:page-size="taxPageSize = $event; loadTaxonomy(1)"
    />
  </div>

  <!-- 2026-07-28:Phase 2 — 自研 mask+div 抽屉改 Element Plus <el-drawer> -->
  <el-drawer
    v-model="drawerVisible"
    direction="rtl"
    size="500px"
    :with-header="false"
  >
    <div v-if="drawerRow" class="ctx-drawer">
      <div class="ctx-drawer-header">
        <div>
          <div class="ctx-drawer-title">分类详情</div>
          <div class="ctx-drawer-sub">
            <span class="ctx-l1-tag" :class="`ctx-l1-${drawerRow.l1}`">{{ drawerRow.l1 }}</span>
            <span class="ctx-drawer-code">{{ drawerRow.l3 }}</span>
            <span class="ctx-drawer-name">{{ drawerRow.name_l3 }}</span>
          </div>
        </div>
        <button class="ctx-drawer-close" @click="drawerVisible = false">×</button>
      </div>
      <div class="ctx-drawer-body">
        <div class="ctx-drawer-section">
          <div class="ctx-drawer-section-title">基础信息</div>
          <div class="ctx-drawer-grid">
            <div class="ctx-drawer-field"><label>L1</label><span>{{ drawerRow.name_l1 || '—' }}</span></div>
            <div class="ctx-drawer-field"><label>L2 分部</label><span>{{ drawerRow.name_l2 || '—' }}</span></div>
            <div class="ctx-drawer-field"><label>GB50500</label><span>{{ drawerRow.gb_50500 || '—' }}</span></div>
          </div>
        </div>
        <div class="ctx-drawer-section">
          <div class="ctx-drawer-section-title">工程属性</div>
          <div class="ctx-drawer-grid">
            <div class="ctx-drawer-field"><label>工程部位</label><span>{{ drawerRow.eng_part || '—' }}</span></div>
            <div class="ctx-drawer-field"><label>工程阶段</label><span>{{ drawerRow.eng_stage || '—' }}</span></div>
            <div class="ctx-drawer-field"><label>主辅材</label><span>{{ drawerRow.main_or_aux || '—' }}</span></div>
          </div>
        </div>
        <div class="ctx-drawer-section">
          <div class="ctx-drawer-section-title">计量计价</div>
          <div class="ctx-drawer-grid">
            <div class="ctx-drawer-field"><label>计量单位</label><span>{{ drawerRow.unit || '—' }}</span></div>
            <div class="ctx-drawer-field"><label>计价单位</label><span>{{ drawerRow.billing_unit || '—' }}</span></div>
            <div class="ctx-drawer-field"><label>计价方式</label><span>{{ drawerRow.cost_method || '—' }}</span></div>
          </div>
        </div>
        <div class="ctx-drawer-section">
          <div class="ctx-drawer-section-title">标准映射</div>
          <div class="ctx-drawer-grid">
            <div class="ctx-drawer-field ctx-drawer-wide"><label>IFC Class</label><span>{{ drawerRow.ifc_class || '—' }}</span></div>
            <div class="ctx-drawer-field ctx-drawer-wide"><label>Uniclass Ss</label><span>{{ drawerRow.uniclass_ss || '—' }}</span></div>
          </div>
        </div>
        <div class="ctx-drawer-actions">
          <button class="ctx-btn ctx-btn-cyan" @click="emitJump(drawerRow.l3); drawerVisible = false">→ 查看关联品种</button>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import AppPagination from './AppPagination.vue'

const emit = defineEmits(['jump-to-breed-map'])
const API = import.meta.env.VITE_API_URL || '/api'

const showHelp = ref(false)
const drawerRow = ref(null)
// 2026-07-28:Phase 2 — el-drawer v-model
const drawerVisible = ref(false)
const taxDefaultSort = ref({ prop: 'l3', order: 'ascending' })

function openDrawer(r) {
  drawerRow.value = r
  drawerVisible.value = true
}

function onTaxSortChange({ prop, order }) {
  // el-table 传 {prop, order:'ascending'|'descending'|null},映射回 {col, dir:'asc'|'desc'}
  sort.value.col = prop
  sort.value.dir = order === 'descending' ? 'desc' : 'asc'
  loadTaxonomy(1)
}
const taxKeyword = ref('')
const taxPageSize = ref(50)
const taxPageSizeOptions = [50, 100, 200]
const taxRows = ref([])
const taxTotal = ref(0)
const taxPage = ref(1)
const taxLoading = ref(false)
const sort = ref({ col: 'l3', dir: 'asc' })

function setTaxSort(col) {
  if (sort.value.col === col) {
    sort.value.dir = sort.value.dir === 'asc' ? 'desc' : 'asc'
  } else {
    sort.value.col = col
    sort.value.dir = 'asc'
  }
  loadTaxonomy(1)
}
function sortIcon(col) {
  if (sort.value.col !== col) return '↕'
  return sort.value.dir === 'asc' ? '↑' : '↓'
}

function debounceLoadTaxonomy(p) {
  clearTimeout(window._ctx_tax_debounce)
  window._ctx_tax_debounce = setTimeout(() => loadTaxonomy(p || 1), 300)
}

async function loadTaxonomy(p = 1) {
  taxLoading.value = true
  try {
    const params = { page: p, page_size: taxPageSize.value }
    if (taxKeyword.value.trim()) params.keyword = taxKeyword.value.trim()
    params.sort_by = sort.value.col
    params.sort_dir = sort.value.dir
    const { data } = await axios.get(`${API}/stats/category-v2-taxonomy`, { params })
    taxRows.value = data.rows || []
    taxTotal.value = data.total || 0
    taxPage.value = p
  } catch (e) { console.error(e) }
  finally { taxLoading.value = false }
}

function clearTaxonomyFilters() {
  taxKeyword.value = ''
  loadTaxonomy(1)
}

function emitJump(l3) {
  emit('jump-to-breed-map', l3)
}

defineExpose({ loadTaxonomy, refresh: () => loadTaxonomy(taxPage.value) })

onMounted(() => { loadTaxonomy(1) })
</script>

<style scoped>
/* 2026-07-28 Phase 2 cleanup:
   表格迁 <el-table> / 抽屉迁 <el-drawer> / 空态走 el-table empty-text。
   已删除: .grid-scroll / .grid-table / .grid-header / .grid-head-cell* / .grid-row / .grid-cell /
            .text-left / .col-name / .col-stdn / .grid-row-empty / .ctx-empty* / 
            .ctx-drawer-mask / @media 内的旧 .filter-bar* / .quick-filters / .filter-drawer / 
            table / thead / tr / td / h1 / h2 / .t-header / .taxonomy-header / .tree-pane / .detail-pane 等。
   修复: 原 .ctx-drawer 移动端覆盖规则被误放在 @media 外,现在归位。 */

/* Toolbar */
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
  height: 36px;
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

.ctx-btn {
  height: 36px; padding: 0 16px; border-radius: 8px; font-size: 13px;
  font-weight: 500; cursor: pointer; border: none; transition: all 0.15s;
  font-family: inherit;
}
.ctx-btn-cyan { background: rgba(37,99,235,0.1); color: var(--primary); border: 1px solid rgba(37,99,235,0.2); }
.ctx-btn-cyan:hover { background: rgba(37,99,235,0.2); }

.ctx-filter-chips {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 12px;
}
.ctx-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 4px 3px 10px;
  background: rgba(37,99,235,0.08);
  color: var(--primary, #2563eb);
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 14px;
  font-size: 11px; font-weight: 600;
}
.ctx-chip-x {
  width: 18px; height: 18px; border-radius: 50%;
  background: rgba(37,99,235,0.15); color: var(--primary);
  border: none; cursor: pointer; font-size: 12px; line-height: 1;
}
.ctx-chip-x:hover { background: var(--primary, #2563eb); color: white; }

.ctx-help {
  background: rgba(241,245,249,0.8); border: 1px solid rgba(37,99,235,0.12);
  border-radius: 10px; padding: 16px 20px; margin-bottom: 12px;
}
.ctx-help-title { font-size: 13px; font-weight: 700; color: var(--primary); margin-bottom: 14px; }
.ctx-help-grid {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  gap: 12px 24px;
}
.ctx-help-item { display: flex; gap: 10px; font-size: 11.5px; line-height: 1.7; }
.ctx-help-key { color: var(--primary); font-weight: 600; white-space: nowrap; min-width: 80px; }
.ctx-help-val { color: var(--text-3); }
.ctx-help-val code {
  font-family: 'Courier New', monospace; font-size: 10px;
  color: var(--primary); background: rgba(37,99,235,0.08);
  border-radius: 3px; padding: 1px 4px; font-weight: 500;
}
.ctx-help-val strong { color: var(--text, #0f172a); font-weight: 600; }

.ctx-slide-enter-active, .ctx-slide-leave-active { transition: all 0.2s ease; overflow: hidden; }
.ctx-slide-enter-from, .ctx-slide-leave-to { opacity: 0; transform: translateY(-6px); }

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

/* Taxonomy-specific 列内容排版(el-table 列插槽用) */
.ctx-l1-tag {
  display: inline-block; min-width: 32px; padding: 2px 8px;
  border-radius: 4px; font-size: 11px; font-weight: 700;
  text-align: center; font-family: 'Courier New', monospace;
}
.ctx-l1-01 { background: rgba(37,99,235,0.12); color: #1d4ed8; }
.ctx-l1-02 { background: rgba(219,39,119,0.12); color: #be185d; }
.ctx-l1-03, .ctx-l1-04, .ctx-l1-05, .ctx-l1-06 {
  background: rgba(124,58,237,0.12); color: #6d28d9;
}
.ctx-l1-07 { background: rgba(234,88,12,0.12); color: #c2410c; }
.ctx-l1-08 { background: rgba(22,163,74,0.12); color: #15803d; }

.ctx-code-text {
  font-family: 'Courier New', monospace; font-size: 12px;
  color: var(--text-2);
}
.ctx-l3-code { color: var(--primary); font-weight: 600; }
.ctx-l3-link { cursor: pointer; transition: color 0.15s; }
.ctx-l3-link:hover { color: var(--primary-dark, #1d4ed8); text-decoration: underline; }
.ctx-l3-arrow { opacity: 0.4; font-size: 11px; transition: all 0.15s; }
.ctx-l3-link:hover .ctx-l3-arrow { opacity: 1; transform: translateX(2px); }
.ctx-gb { color: var(--status-ok); font-weight: 600; }
.ctx-std-name { font-size: 11px; color: var(--text-2); font-weight: 500; display: inline-block; max-width: 100%; }
.ctx-name-stack { display: flex; flex-direction: column; gap: 2px; padding-left: 8px; border-left: 2px solid rgba(37,99,235,0.18); }
.ctx-name-l1 { font-size: 11px; color: var(--text-3); font-family: 'Courier New', monospace; }
.ctx-name-l3 { font-size: 13px; font-weight: 600; color: var(--text, #0f172a); line-height: 1.3; }
.ctx-tag {
  display: inline-block; padding: 1px 7px; border-radius: 3px;
  font-size: 11px; font-weight: 600;
}
.ctx-tag-part-基础 { background: rgba(99,102,241,0.1); color: #6366f1; }
.ctx-tag-part-主体 { background: rgba(37,99,235,0.1); color: var(--primary); }
.ctx-tag-part-装饰 { background: rgba(236,72,153,0.1); color: #ec4899; }
.ctx-tag-part-屋面 { background: rgba(245,158,11,0.1); color: #f59e0b; }
.ctx-tag-part-其他 { background: rgba(15,23,42,0.06); color: var(--text-3); }
.ctx-main-aux {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600;
}
.ctx-ma-主材 { background: rgba(34,197,94,0.12); color: #16a34a; }
.ctx-ma-辅材 { background: rgba(148,163,184,0.15); color: #475569; }
.ctx-unit {
  font-family: 'Courier New', monospace; font-size: 12px;
  font-weight: 600; color: var(--text-2);
}

/* Drawer(el-drawer 内部内容容器) */
.ctx-drawer {
  width: 460px; max-width: 90vw; height: 100vh;
  background: var(--surface); border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  box-shadow: -8px 0 24px rgba(15,23,42,0.08);
}
.ctx-drawer-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 20px 24px; border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(37,99,235,0.04), transparent);
}
.ctx-drawer-title { font-size: 13px; font-weight: 700; color: var(--primary); margin-bottom: 8px; }
.ctx-drawer-sub { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ctx-drawer-code {
  font-family: 'Courier New', monospace; font-size: 13px; font-weight: 700;
  color: var(--primary);
}
.ctx-drawer-name { font-size: 15px; font-weight: 600; color: var(--text, #0f172a); }
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

/* ── 移动端(el-drawer / ctx-drawer-grid 单列) ── */
@media (max-width: 768px) {
  .ctx-drawer { width: 92vw !important; max-width: 360px !important; }
  .ctx-drawer-grid { grid-template-columns: 1fr !important; }
}
</style>
