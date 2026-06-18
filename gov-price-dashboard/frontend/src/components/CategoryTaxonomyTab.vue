<template>
  <!-- Toolbar -->
  <div class="ctx-toolbar">
    <div class="ctx-toolbar-left">
      <div class="ctx-search-wrap">
        <span class="ctx-search-icon">🔍</span>
        <input
          class="ctx-input"
          v-model="taxKeyword"
          placeholder="搜索名称 / 编码 / GB50500 / IFC..."
          @input="debounceLoadTaxonomy(1)"
        />
      </div>
      <CustomSelect
        v-model="taxL1Filter"
        :options="taxL1Options.map(o => ({ key: o, label: o }))"
        placeholder="全部 L1"
        :searchable="false"
        @change="loadTaxonomy(1)"
      />
      <CustomSelect
        v-model="taxL2Filter"
        :options="taxL2FilteredOptions.map(o => ({ key: o, label: o }))"
        placeholder="全部 L2"
        :searchable="false"
        @change="loadTaxonomy(1)"
      />
    </div>
    <div class="ctx-toolbar-right">
      <div class="ctx-density-toggle" title="表格密度">
        <button :class="{ active: taxDensity==='compact' }" @click="taxDensity='compact'">紧凑</button>
        <button :class="{ active: taxDensity==='standard' }" @click="taxDensity='standard'">标准</button>
        <button :class="{ active: taxDensity==='loose' }" @click="taxDensity='loose'">宽松</button>
      </div>
      <button class="ctx-btn ctx-btn-red" @click="clearTaxonomyFilters" :disabled="taxLoading">
        🗑️ 清空筛选
      </button>
      <button class="ctx-btn ctx-btn-cyan" @click="showHelp = !showHelp">
        {{ showHelp ? '🔼 收起' : '📖 使用说明' }}
      </button>
    </div>
  </div>

  <!-- Active Filter Chips -->
  <div class="ctx-filter-chips" v-if="taxActiveChips.length || taxKeyword">
    <span v-if="taxKeyword" class="ctx-chip">
      搜索: "{{ taxKeyword }}"
      <button class="ctx-chip-x" @click="taxKeyword=''; debounceLoadTaxonomy(1)" title="移除">×</button>
    </span>
    <span v-for="chip in taxActiveChips" :key="chip.key" class="ctx-chip">
      {{ chip.label }}: {{ chip.value }}
      <button class="ctx-chip-x" @click="chip.action" :title="`移除 ${chip.label}`">×</button>
    </span>
    <button class="ctx-chip-clear" @click="clearTaxonomyFilters">清空全部</button>
    <span style="flex:1"></span>
    <span style="font-size:11px;color:var(--text-3);font-family:'Courier New',monospace;">
      排序: {{ taxSort.col === 'l3' ? 'L3' : taxSort.col }} {{ taxSort.dir==='asc'?'↑':'↓' }}
    </span>
  </div>

  <!-- 使用说明 -->
  <Transition name="ctx-slide">
    <div class="ctx-help" v-if="showHelp">
      <div class="ctx-help-title">📖 分类体系说明</div>
      <div class="ctx-help-grid">
        <div class="ctx-help-item">
          <span class="ctx-help-key">数据源</span>
          <span class="ctx-help-val">
            <strong>唯一来源</strong>：<code>category_v2_rules.db</code><br/>
            <strong>表 1</strong> <code>category_v2</code>：3 级分类法（64 行）<br/>
            <strong>表 2</strong> <code>breed_l3_map</code>：品种→L3 映射（4073 行）
          </span>
        </div>
        <div class="ctx-help-item">
          <span class="ctx-help-key">L1-L3 含义</span>
          <span class="ctx-help-val">
            <strong>L1</strong>：8 大类（建筑工程 / 安装工程 / ...）<br/>
            <strong>L2</strong>：分部工程（34 个）<br/>
            <strong>L3</strong>：分项工程（64 个，含 GB50500 编码）
          </span>
        </div>
        <div class="ctx-help-item">
          <span class="ctx-help-key">标准映射</span>
          <span class="ctx-help-val">
            <code>gb_50500</code> — GB 50500 工程量清单规范编码<br/>
            <code>ifc_class</code> — IFC 国际 BIM 分类<br/>
            <code>uniclass_ss</code> — Uniclass 分类代码
          </span>
        </div>
        <div class="ctx-help-item">
          <span class="ctx-help-key">映射来源</span>
          <span class="ctx-help-val">
            <code>v1_translated</code> (4068) — 从 v1 分类规则自动翻译<br/>
            <code>ai_v2</code> (5) — AI 直接生成 L3 分类<br/>
            <strong>置信度</strong>：默认 0.7，AI 高置信度为 0.8-0.93
          </span>
        </div>
        <div class="ctx-help-item">
          <span class="ctx-help-key">主辅材</span>
          <span class="ctx-help-val">
            <code>main_or_aux</code> 区分 <strong>主材 / 辅材</strong><br/>
            <code>eng_part</code> 标记 <strong>基础 / 主体 / 装饰</strong> 等工程部位<br/>
            <code>eng_stage</code> 区分 <strong>设计 / 施工 / 运维</strong> 阶段
          </span>
        </div>
        <div class="ctx-help-item">
          <span class="ctx-help-key">计量计价</span>
          <span class="ctx-help-val">
            <code>unit</code> — 自然计量单位（如 <code>m³</code> / <code>t</code>）<br/>
            <code>billing_unit</code> — 计价单位（可能不同，如 <code>100m</code>）<br/>
            <code>cost_method</code> — 计价方式（清单 / 定额 / 清单+定额）
          </span>
        </div>
      </div>
    </div>
  </Transition>

  <!-- Table -->
  <div class="ctx-card" :class="`ctx-density-${taxDensity}`">
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th style="width:50px" @click="setTaxSort('l1')">L1 <span class="sort-icon" v-if="taxSort.col==='l1'">{{ taxSort.dir==='asc'?'↑':'↓' }}</span></th>
            <th style="width:70px" @click="setTaxSort('l2')">L2 <span class="sort-icon" v-if="taxSort.col==='l2'">{{ taxSort.dir==='asc'?'↑':'↓' }}</span></th>
            <th style="width:100px" @click="setTaxSort('l3')">L3 <span class="sort-icon" v-if="taxSort.col==='l3'">{{ taxSort.dir==='asc'?'↑':'↓' }}</span></th>
            <th style="width:78px" class="no-sort">GB50500</th>
            <th class="text-left" @click="setTaxSort('name_l3')">分类名称 <span class="sort-icon" v-if="taxSort.col==='name_l3'">{{ taxSort.dir==='asc'?'↑':'↓' }}</span></th>
            <th style="width:80px" class="no-sort">工程部位</th>
            <th style="width:80px" class="no-sort">主辅材</th>
            <th style="width:56px" class="no-sort">单位</th>
            <th style="width:140px" class="text-left no-sort">IFC</th>
            <th style="width:140px" class="text-left no-sort">Uniclass</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="taxLoading">
            <td colspan="10" class="ctx-empty">加载中...</td>
          </tr>
          <tr v-else-if="!taxRows.length">
            <td colspan="10" class="ctx-empty">
              <div class="ctx-empty-art">🗂️</div>
              <div class="ctx-empty-title">暂无分类条目</div>
              <div class="ctx-empty-hint">试试调整筛选条件或清空全部</div>
              <button class="ctx-btn ctx-btn-cyan" @click="clearTaxonomyFilters" style="margin-top:12px">🔍 清空筛选</button>
            </td>
          </tr>
          <tr v-for="r in taxRows" :key="`${r.l1}-${r.l2}-${r.l3}`" class="ctx-row" @click="drawerRow = r" style="cursor:pointer" v-show="!taxLoading && taxRows.length">
            <td><span class="ctx-l1-tag" :class="`ctx-l1-${r.l1}`">{{ r.l1 }}</span></td>
            <td><span class="ctx-code-text">{{ r.l2 }}</span></td>
            <td><span class="ctx-code-text ctx-l3-code ctx-l3-link" @click.stop="emitJump(r.l3)" title="查看此 L3 关联的品种">{{ r.l3 }} <span class="ctx-l3-arrow">→</span></span></td>
            <td><span class="ctx-code-text ctx-gb">{{ r.gb_50500 || '—' }}</span></td>
            <td class="text-left no-ellipsis">
              <div class="ctx-name-stack">
                <span class="ctx-name-l1">› {{ r.name_l1 || '—' }}</span>
                <span class="ctx-name-l3">{{ r.name_l3 || r.name_l2 || r.l3 }}</span>
              </div>
            </td>
            <td>
              <div class="ctx-tags">
                <span class="ctx-tag" :class="`ctx-tag-part-${r.eng_part}`">{{ r.eng_part || '—' }}</span>
              </div>
            </td>
            <td>
              <span class="ctx-main-aux" :class="`ctx-ma-${r.main_or_aux}`">{{ r.main_or_aux || '—' }}</span>
            </td>
            <td><span class="ctx-unit">{{ r.unit || '—' }}</span></td>
            <td class="text-left" :title="r.ifc_class">{{ r.ifc_class || '—' }}</td>
            <td class="text-left" :title="r.uniclass_ss">{{ r.uniclass_ss || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <AppPagination
      :current="taxPage"
      :total="taxTotal"
      :page-size="50"
      info-template="第 {from}-{to} 条 / 共 {total} 条"
      @change="loadTaxonomy"
    />
  </div>

  <!-- Row Detail Drawer -->
  <div v-if="drawerRow" class="ctx-drawer-mask" @click.self="drawerRow = null">
    <div class="ctx-drawer">
      <div class="ctx-drawer-header">
        <div>
          <div class="ctx-drawer-title">分类详情</div>
          <div class="ctx-drawer-sub">
            <span class="ctx-l1-tag" :class="`ctx-l1-${drawerRow.l1}`">{{ drawerRow.l1 }}</span>
            <span class="ctx-drawer-code">{{ drawerRow.l3 }}</span>
            <span class="ctx-drawer-name">{{ drawerRow.name_l3 }}</span>
          </div>
        </div>
        <button class="ctx-drawer-close" @click="drawerRow = null">×</button>
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
          <button class="ctx-btn ctx-btn-cyan" @click="emitJump(drawerRow.l3); drawerRow = null">→ 查看关联品种</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import CustomSelect from './CustomSelect.vue'
import AppPagination from './AppPagination.vue'

const emit = defineEmits(['jump-to-breed-map'])

const API = import.meta.env.VITE_API_URL || '/api'

// ── 状态 ──
const showHelp = ref(false)
const drawerRow = ref(null)
const taxDensity = ref('standard')
const taxKeyword = ref('')
const taxL1Filter = ref('')
const taxL2Filter = ref('')
const taxL1Options = ref([])
const taxL2OptionsRaw = ref([])
const taxRows = ref([])
const taxTotal = ref(0)
const taxPage = ref(1)
const taxLoading = ref(false)
const taxSort = ref({ col: 'l3', dir: 'asc' })

function setTaxSort(col) {
  if (taxSort.value.col === col) {
    taxSort.value.dir = taxSort.value.dir === 'asc' ? 'desc' : 'asc'
  } else {
    taxSort.value.col = col
    taxSort.value.dir = 'asc'
  }
  loadTaxonomy(1)
}

const taxActiveChips = computed(() => {
  const chips = []
  if (taxL1Filter.value) {
    chips.push({
      key: 'l1', label: 'L1', value: taxL1Filter.value,
      action: () => { taxL1Filter.value = ''; loadTaxonomy(1) }
    })
  }
  if (taxL2Filter.value) {
    chips.push({
      key: 'l2', label: 'L2', value: taxL2Filter.value,
      action: () => { taxL2Filter.value = ''; loadTaxonomy(1) }
    })
  }
  return chips
})

const taxL2FilteredOptions = computed(() => {
  if (!taxL1Filter.value) {
    return [...new Set(taxL2OptionsRaw.value.map(o => o.l2))]
  }
  return taxL2OptionsRaw.value.filter(o => o.l1 === taxL1Filter.value).map(o => o.l2)
})

function debounceLoadTaxonomy(p) {
  clearTimeout(window._ctx_tax_debounce)
  window._ctx_tax_debounce = setTimeout(() => loadTaxonomy(p || 1), 300)
}

async function loadTaxonomy(p = 1) {
  taxLoading.value = true
  try {
    const params = { page: p, page_size: 50 }
    if (taxKeyword.value.trim()) params.keyword = taxKeyword.value.trim()
    if (taxL1Filter.value) params.l1 = taxL1Filter.value
    if (taxL2Filter.value) params.l2 = taxL2Filter.value
    params.sort_by = taxSort.value.col
    params.sort_dir = taxSort.value.dir
    const { data } = await axios.get(`${API}/stats/category-v2-taxonomy`, { params })
    taxRows.value = data.rows || []
    taxTotal.value = data.total || 0
    taxPage.value = p
    if (!taxL1Options.value.length) {
      taxL1Options.value = data.l1_options || []
      taxL2OptionsRaw.value = data.l2_options || []
    }
  } catch (e) { console.error(e) }
  finally { taxLoading.value = false }
}

function clearTaxonomyFilters() {
  taxKeyword.value = ''
  taxL1Filter.value = ''
  taxL2Filter.value = ''
  loadTaxonomy(1)
}

// 跨 tab 跳转（emit 给父）
function emitJump(l3) {
  emit('jump-to-breed-map', l3)
}

// 暴露方法给父组件调用（用于外部触发刷新）
defineExpose({ loadTaxonomy, refresh: () => loadTaxonomy(taxPage.value) })

onMounted(() => {
  loadTaxonomy(1)
})
</script>

<style scoped>
/* Toolbar */
.ctx-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 14px; gap: 12px;
}
.ctx-toolbar-left { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.ctx-toolbar-right { display: flex; gap: 8px; }
.ctx-search-wrap { position: relative; }
.ctx-search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); font-size: 13px; }
.ctx-input {
  height: 36px; background: #e2e8f0; border: 1px solid rgba(241,245,249,0.6);
  border-radius: 8px; padding: 0 12px; font-size: 13px; color: #1e293b; outline: none;
  font-family: inherit;
}
.ctx-input::placeholder { color: #475569; }
.ctx-input:focus { border-color: rgba(37,99,235,0.5); background: rgba(37,99,235,0.05); }
.ctx-search-wrap .ctx-input { padding-left: 32px; width: 220px; }

/* Density toggle */
.ctx-density-toggle {
  display: inline-flex; height: 36px; border-radius: 8px; overflow: hidden;
  border: 1px solid rgba(15,23,42,0.08); background: var(--surface);
}
.ctx-density-toggle button {
  padding: 0 12px; border: none; background: transparent;
  font-size: 12px; color: var(--text-2); cursor: pointer;
  font-family: inherit; transition: all 0.15s;
}
.ctx-density-toggle button:hover { background: var(--surface-2); }
.ctx-density-toggle button.active { background: var(--primary); color: white; font-weight: 600; }

/* Buttons */
.ctx-btn {
  height: 36px; padding: 0 16px; border-radius: 8px; font-size: 13px;
  font-weight: 500; cursor: pointer; border: none; transition: all 0.15s;
  font-family: inherit;
}
.ctx-btn-cyan { background: rgba(37,99,235,0.1); color: var(--primary); border: 1px solid rgba(37,99,235,0.2); }
.ctx-btn-cyan:hover { background: rgba(37,99,235,0.2); }
.ctx-btn-red { background: rgba(248,113,113,0.1); color: var(--status-alert); border: 1px solid rgba(248,113,113,0.2); }
.ctx-btn-red:hover { background: rgba(248,113,113,0.2); }
.ctx-btn-red:disabled { opacity: 0.4; cursor: not-allowed; }

/* Filter chips */
.ctx-filter-chips {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 12px; flex-wrap: wrap;
  min-height: 28px;
}
.ctx-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 4px 4px 10px;
  background: rgba(37,99,235,0.08);
  color: var(--primary);
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 14px;
  font-size: 11px; font-weight: 600;
  font-family: 'Courier New', monospace;
}
.ctx-chip-x {
  width: 18px; height: 18px; border-radius: 50%;
  background: rgba(37,99,235,0.15); color: var(--primary);
  border: none; cursor: pointer; font-size: 12px; line-height: 1;
  display: inline-flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.ctx-chip-x:hover { background: var(--primary); color: white; }
.ctx-chip-clear {
  background: transparent; border: none; color: var(--text-3);
  font-size: 11px; cursor: pointer; padding: 4px 8px;
  text-decoration: underline; text-underline-offset: 2px;
}
.ctx-chip-clear:hover { color: var(--text); }

/* Help */
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
.ctx-help-val strong { color: #1e293b; font-weight: 600; }

/* Card / Table */
.ctx-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden; box-shadow: var(--shadow);
}
.table-scroll { overflow-x: auto; }
.ctx-row { cursor: pointer; }
.ctx-density-compact.data-table td { padding: 5px 14px; }
.ctx-density-compact.data-table th { padding: 7px 14px; }
.ctx-density-compact.data-table { font-size: 12px; }
.ctx-density-loose.data-table td { padding: 16px 14px; }
.ctx-density-loose.data-table th { padding: 14px 14px; }
.ctx-density-loose.data-table { font-size: 14px; }
.ctx-empty { text-align: center; color: #475569; padding: 48px 36px !important; }
.ctx-empty-art { font-size: 48px; opacity: 0.6; margin-bottom: 12px; }
.ctx-empty-title { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.ctx-empty-hint { font-size: 12px; color: var(--text-3); }

/* Taxonomy-specific */
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
.ctx-name-stack { display: flex; flex-direction: column; gap: 2px; padding-left: 10px; border-left: 2px solid rgba(37,99,235,0.18); }
.ctx-name-l1 { font-size: 11px; color: var(--text-3); font-family: 'Courier New', monospace; }
.ctx-name-l3 { font-size: 13px; font-weight: 600; color: #1e293b; line-height: 1.3; }
.ctx-tags { display: flex; gap: 4px; flex-wrap: wrap; }
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
.ctx-std-text {
  font-family: 'Courier New', monospace; font-size: 11px;
  color: var(--text-3); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; max-width: 150px;
}

/* Slide transition for help */
.ctx-slide-enter-active, .ctx-slide-leave-active { transition: all 0.2s ease; overflow: hidden; }
.ctx-slide-enter-from, .ctx-slide-leave-to { opacity: 0; transform: translateY(-6px); }

/* Drawer */
.ctx-drawer-mask {
  position: fixed; inset: 0; background: rgba(15,23,42,0.4);
  display: flex; justify-content: flex-end; z-index: 9999;
  backdrop-filter: blur(2px);
}
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
.ctx-drawer-name { font-size: 15px; font-weight: 600; color: #1e293b; }
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
.ctx-drawer-field span { font-size: 13px; color: #1e293b; font-weight: 500; }
.ctx-drawer-actions { padding-top: 8px; border-top: 1px solid var(--border); }
</style>