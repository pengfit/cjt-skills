<template>
  <div class="cv2-page">
    <!-- Header -->
    <div class="cv2-header">
      <div class="cv2-header-left">
        <div class="cv2-title">🗂️ 分类体系 v2</div>
        <div class="cv2-subtitle">
          4 级分类法（L1 / L2 / L3 / L4）+ 品种→L3 映射规则，
          来源 <code>category_v2_rules.db</code>，覆盖 8 大类 / 64 个 L3
        </div>
      </div>
      <div class="cv2-header-stats">
        <div class="cv2-stat">
          <span class="cv2-stat-val">{{ stats.taxonomy.l1 || 0 }}</span>
          <span class="cv2-stat-key">一级</span>
        </div>
        <div class="cv2-stat">
          <span class="cv2-stat-val">{{ stats.taxonomy.l3 || 0 }}</span>
          <span class="cv2-stat-key">三级分类</span>
        </div>
        <div class="cv2-stat">
          <span class="cv2-stat-val">{{ stats.map.total.toLocaleString() }}</span>
          <span class="cv2-stat-key">品种映射</span>
        </div>
        <div class="cv2-stat" :title="`L3 命中率：${stats.map.l3_in_taxonomy} / ${stats.map.l3_in_taxonomy + stats.map.l3_not_in_taxonomy}`">
          <span class="cv2-stat-val cv2-stat-rate">
            {{ hitRate }}%
          </span>
          <span class="cv2-stat-key">L3 命中率</span>
        </div>
      </div>
    </div>

    <!-- Sub Tabs -->
    <div class="cv2-subtabs">
      <button class="cv2-subtab" :class="{ active: subTab === 'taxonomy' }" @click="subTab = 'taxonomy'">
        <span class="cv2-subtab-dot"></span>
        分类法
        <span class="cv2-subtab-hint">4 级分类体系 / 64 行</span>
      </button>
      <button class="cv2-subtab" :class="{ active: subTab === 'map' }" @click="subTab = 'map'">
        <span class="cv2-subtab-dot"></span>
        品种映射
        <span class="cv2-subtab-hint">breed → L3 / 4073 条</span>
      </button>
    </div>

    <!-- Tab 1: 分类法 -->
    <template v-if="subTab === 'taxonomy'">
      <!-- Toolbar -->
      <div class="cv2-toolbar">
        <div class="cv2-toolbar-left">
          <div class="cv2-search-wrap">
            <span class="cv2-search-icon">🔍</span>
            <input
              class="cv2-input"
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
        <div class="cv2-toolbar-right">
          <button class="cv2-btn cv2-btn-red" @click="clearTaxonomyFilters" :disabled="taxLoading">
            🗑️ 清空筛选
          </button>
          <button class="cv2-btn cv2-btn-cyan" @click="showHelp = !showHelp">
            {{ showHelp ? '🔼 收起' : '📖 使用说明' }}
          </button>
        </div>
      </div>

      <!-- 使用说明 -->
      <Transition name="cv2-slide">
        <div class="cv2-help" v-if="showHelp">
          <div class="cv2-help-title">📖 分类体系 v2 说明</div>
          <div class="cv2-help-grid">
            <div class="cv2-help-item">
              <span class="cv2-help-key">数据源</span>
              <span class="cv2-help-val">
                <strong>唯一来源</strong>：<code>category_v2_rules.db</code><br/>
                <strong>表 1</strong> <code>category_v2</code>：4 级分类法（64 行）<br/>
                <strong>表 2</strong> <code>breed_l3_map</code>：品种→L3 映射（4073 行）
              </span>
            </div>
            <div class="cv2-help-item">
              <span class="cv2-help-key">L1-L4 含义</span>
              <span class="cv2-help-val">
                <strong>L1</strong>：8 大类（建筑工程 / 安装工程 / ...）<br/>
                <strong>L2</strong>：分部工程（34 个）<br/>
                <strong>L3</strong>：分项工程（64 个，含 GB50500 编码）<br/>
                <strong>L4</strong>：当前 0 条，全部标记 <code>UNCLASSIFIED</code>
              </span>
            </div>
            <div class="cv2-help-item">
              <span class="cv2-help-key">标准映射</span>
              <span class="cv2-help-val">
                <code>gb_50500</code> — GB 50500 工程量清单规范编码<br/>
                <code>quota_ref</code> — 定额引用（如 <code>1-1</code> / <code>4-1</code>）<br/>
                <code>ifc_class</code> — IFC 国际 BIM 分类<br/>
                <code>uniclass_ss</code> — Uniclass 分类代码
              </span>
            </div>
            <div class="cv2-help-item">
              <span class="cv2-help-key">映射来源</span>
              <span class="cv2-help-val">
                <code>v1_translated</code> (4068) — 从 v1 分类规则自动翻译<br/>
                <code>ai_v2</code> (5) — AI 直接生成 v2 L3 分类<br/>
                <strong>置信度</strong>：默认 0.7，AI 高置信度为 0.8-0.93
              </span>
            </div>
            <div class="cv2-help-item">
              <span class="cv2-help-key">主辅材</span>
              <span class="cv2-help-val">
                <code>main_or_aux</code> 区分 <strong>主材 / 辅材</strong><br/>
                <code>eng_part</code> 标记 <strong>基础 / 主体 / 装饰</strong> 等工程部位<br/>
                <code>eng_stage</code> 区分 <strong>设计 / 施工 / 运维</strong> 阶段
              </span>
            </div>
            <div class="cv2-help-item">
              <span class="cv2-help-key">计量计价</span>
              <span class="cv2-help-val">
                <code>unit</code> — 自然计量单位（如 <code>m³</code> / <code>t</code>）<br/>
                <code>billing_unit</code> — 计价单位（可能不同，如 <code>100m</code>）<br/>
                <code>cost_method</code> — 计价方式（清单 / 定额 / 清单+定额）
              </span>
            </div>
          </div>
        </div>
      </Transition>

      <!-- Table -->
      <div class="cv2-card">
        <div class="table-scroll">
          <table class="cv2-table">
            <thead>
              <tr>
                <th style="width:60px">L1</th>
                <th style="width:80px">L2</th>
                <th style="width:90px">L3</th>
                <th style="width:90px">GB50500</th>
                <th style="width:60px">定额</th>
                <th>分类名称</th>
                <th style="width:100px">工程部位</th>
                <th style="width:90px">主辅材</th>
                <th style="width:70px">单位</th>
                <th style="width:120px">IFC</th>
                <th style="width:120px">Uniclass</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="taxLoading">
                <td colspan="11" class="cv2-empty">加载中...</td>
              </tr>
              <tr v-else-if="!taxRows.length">
                <td colspan="11" class="cv2-empty">暂无分类条目</td>
              </tr>
              <tr v-else v-for="r in taxRows" :key="`${r.l1}-${r.l2}-${r.l3}-${r.l4}`" class="cv2-row">
                <td><span class="cv2-l1-tag">{{ r.l1 }}</span></td>
                <td><span class="cv2-code-text">{{ r.l2 }}</span></td>
                <td><span class="cv2-code-text cv2-l3-code">{{ r.l3 }}</span></td>
                <td><span class="cv2-code-text cv2-gb">{{ r.gb_50500 || '—' }}</span></td>
                <td><span class="cv2-quota">{{ r.quota_ref || '—' }}</span></td>
                <td>
                  <div class="cv2-name-stack">
                    <span class="cv2-name-l1">{{ r.name_l1 || '—' }}</span>
                    <span class="cv2-name-l3">{{ r.name_l3 || r.name_l2 || r.l3 }}</span>
                  </div>
                </td>
                <td>
                  <div class="cv2-tags">
                    <span class="cv2-tag" :class="`tag-part-${r.eng_part}`">{{ r.eng_part || '—' }}</span>
                  </div>
                </td>
                <td>
                  <span class="cv2-main-aux" :class="`ma-${r.main_or_aux}`">{{ r.main_or_aux || '—' }}</span>
                </td>
                <td><span class="cv2-unit">{{ r.unit || '—' }}</span></td>
                <td class="cv2-std-text" :title="r.ifc_class">{{ r.ifc_class || '—' }}</td>
                <td class="cv2-std-text" :title="r.uniclass_ss">{{ r.uniclass_ss || '—' }}</td>
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
    </template>

    <!-- Tab 2: 品种映射 -->
    <template v-else-if="subTab === 'map'">
      <!-- Toolbar -->
      <div class="cv2-toolbar">
        <div class="cv2-toolbar-left">
          <div class="cv2-search-wrap">
            <span class="cv2-search-icon">🔍</span>
            <input
              class="cv2-input"
              v-model="mapKeyword"
              placeholder="搜索品种名..."
              @input="debounceLoadMap(1)"
            />
          </div>
          <CustomSelect
            v-model="mapL3Filter"
            :options="mapL3Options.map(o => ({ key: o, label: o }))"
            placeholder="全部 L3"
            :searchable="true"
            @change="loadMap(1)"
          />
          <CustomSelect
            v-model="mapSourceFilter"
            :options="mapSourceOptions.map(o => ({ key: o, label: o }))"
            placeholder="全部来源"
            :searchable="false"
            @change="loadMap(1)"
          />
          <div class="cv2-conf-wrap">
            <span class="cv2-conf-label">置信度 ≥</span>
            <input
              class="cv2-conf-input"
              type="number"
              step="0.05"
              min="0"
              max="1"
              v-model.number="mapMinConf"
              @change="loadMap(1)"
            />
          </div>
        </div>
        <div class="cv2-toolbar-right">
          <button class="cv2-btn cv2-btn-red" @click="clearMapFilters" :disabled="mapLoading">
            🗑️ 清空筛选
          </button>
        </div>
      </div>

      <!-- Table -->
      <div class="cv2-card">
        <div class="table-scroll">
          <table class="cv2-table">
            <thead>
              <tr>
                <th style="width:50%">品种</th>
                <th style="width:90px">L3</th>
                <th>L3 名称</th>
                <th style="width:90px">来源</th>
                <th style="width:80px">置信度</th>
                <th style="width:140px">更新时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="mapLoading">
                <td colspan="6" class="cv2-empty">加载中...</td>
              </tr>
              <tr v-else-if="!mapRows.length">
                <td colspan="6" class="cv2-empty">暂无映射</td>
              </tr>
              <tr v-else v-for="r in mapRows" :key="r.breed_clean" class="cv2-row">
                <td><span class="cv2-breed-text">{{ r.breed_clean }}</span></td>
                <td><span class="cv2-code-text cv2-l3-code">{{ r.l3 }}</span></td>
                <td>
                  <div class="cv2-name-stack">
                    <span class="cv2-name-l1">{{ r.name_l1 || '—' }}</span>
                    <span class="cv2-name-l3">{{ r.name_l3 || '—' }}</span>
                  </div>
                </td>
                <td>
                  <span class="cv2-src" :class="`src-${r.source}`">{{ sourceLabel(r.source) }}</span>
                </td>
                <td>
                  <span class="cv2-conf" :class="confClass(r.confidence)">
                    {{ (r.confidence ?? 1).toFixed(2) }}
                  </span>
                </td>
                <td class="cv2-date">{{ formatDate(r.updated_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Pagination -->
        <AppPagination
          :current="mapPage"
          :total="mapTotal"
          :page-size="50"
          info-template="第 {from}-{to} 条 / 共 {total} 条"
          @change="loadMap"
        />
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import axios from 'axios'
import CustomSelect from './CustomSelect.vue'
import AppPagination from './AppPagination.vue'

const API = import.meta.env.VITE_API_URL || '/api'

// ── 顶部统计 ──
const stats = ref({
  taxonomy: { l1: 0, l2: 0, l3: 0, l4: 0 },
  map: { total: 0, l3_in_taxonomy: 0, l3_not_in_taxonomy: 0 },
})

const hitRate = computed(() => {
  const inT = stats.value.map.l3_in_taxonomy
  const out = stats.value.map.l3_not_in_taxonomy
  const tot = inT + out
  if (!tot) return '0.0'
  return ((inT / tot) * 100).toFixed(1)
})

const subTab = ref('taxonomy')
const showHelp = ref(false)

// ── 分类法 Tab 状态 ──
const taxKeyword = ref('')
const taxL1Filter = ref('')
const taxL2Filter = ref('')
const taxL1Options = ref([])
const taxL2OptionsRaw = ref([])  // [{l1, l2}]
const taxRows = ref([])
const taxTotal = ref(0)
const taxPage = ref(1)
const taxLoading = ref(false)

const taxL2FilteredOptions = computed(() => {
  if (!taxL1Filter.value) {
    // 没选 L1 时显示所有不重复 L2
    return [...new Set(taxL2OptionsRaw.value.map(o => o.l2))]
  }
  return taxL2OptionsRaw.value.filter(o => o.l1 === taxL1Filter.value).map(o => o.l2)
})

// ── 品种映射 Tab 状态 ──
const mapKeyword = ref('')
const mapL3Filter = ref('')
const mapSourceFilter = ref('')
const mapMinConf = ref(0)
const mapL3Options = ref([])
const mapSourceOptions = ref([])
const mapRows = ref([])
const mapTotal = ref(0)
const mapPage = ref(1)
const mapLoading = ref(false)

// ── 工具 ──
const srcLabels = {
  v1_translated: 'v1翻译',
  ai_v2: 'AI v2',
  manual: '手动',
}
function sourceLabel(s) { return srcLabels[s] || s }
function confClass(c) {
  if (c == null || c >= 0.85) return 'conf-high'
  if (c >= 0.7) return 'conf-mid'
  return 'conf-low'
}
function formatDate(s) {
  if (!s) return '—'
  return String(s).slice(0, 19).replace('T', ' ')
}

function debounceLoadTaxonomy(p) {
  clearTimeout(window._cv2_tax_debounce)
  window._cv2_tax_debounce = setTimeout(() => loadTaxonomy(p || 1), 300)
}
function debounceLoadMap(p) {
  clearTimeout(window._cv2_map_debounce)
  window._cv2_map_debounce = setTimeout(() => loadMap(p || 1), 300)
}

// ── API 调用 ──
async function loadStats() {
  try {
    const { data } = await axios.get(`${API}/stats/category-v2-stats`)
    if (data.ok) stats.value = data
  } catch (e) { console.error(e) }
}

async function loadTaxonomy(p = 1) {
  taxLoading.value = true
  try {
    const params = { page: p, page_size: 50 }
    if (taxKeyword.value.trim()) params.keyword = taxKeyword.value.trim()
    if (taxL1Filter.value) params.l1 = taxL1Filter.value
    if (taxL2Filter.value) params.l2 = taxL2Filter.value
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

async function loadMap(p = 1) {
  mapLoading.value = true
  try {
    const params = { page: p, page_size: 50 }
    if (mapKeyword.value.trim()) params.keyword = mapKeyword.value.trim()
    if (mapL3Filter.value) params.l3 = mapL3Filter.value
    if (mapSourceFilter.value) params.source = mapSourceFilter.value
    if (mapMinConf.value && mapMinConf.value > 0) params.min_confidence = mapMinConf.value
    const { data } = await axios.get(`${API}/stats/category-v2-breed-map`, { params })
    mapRows.value = data.rows || []
    mapTotal.value = data.total || 0
    mapPage.value = p
    if (!mapL3Options.value.length) {
      mapL3Options.value = data.l3_options || []
      mapSourceOptions.value = data.source_options || []
    }
  } catch (e) { console.error(e) }
  finally { mapLoading.value = false }
}

function clearTaxonomyFilters() {
  taxKeyword.value = ''
  taxL1Filter.value = ''
  taxL2Filter.value = ''
  loadTaxonomy(1)
}

function clearMapFilters() {
  mapKeyword.value = ''
  mapL3Filter.value = ''
  mapSourceFilter.value = ''
  mapMinConf.value = 0
  loadMap(1)
}

onMounted(() => {
  loadStats()
  loadTaxonomy(1)
})

// 切换到品种映射 tab 时按需加载
watch(subTab, (v) => {
  if (v === 'map' && !mapL3Options.value.length) {
    loadMap(1)
  }
})
</script>

<style scoped>
.cv2-page { padding: 0 28px 28px; }

/* Header */
.cv2-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 22px 0 16px;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 16px;
}
.cv2-title { font-size: 18px; font-weight: 700; color: #1e293b; }
.cv2-subtitle { font-size: 12px; color: var(--text-3); margin-top: 3px; line-height: 1.6; }
.cv2-subtitle code {
  font-family: 'Courier New', monospace; font-size: 10px;
  color: var(--primary); background: rgba(37,99,235,0.08);
  border-radius: 3px; padding: 1px 4px; font-weight: 500;
}
.cv2-header-stats { display: flex; gap: 20px; }
.cv2-stat { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.cv2-stat-val { font-size: 18px; font-weight: 700; color: var(--primary); }
.cv2-stat-rate { color: var(--status-ok); }
.cv2-stat-key { font-size: 11px; color: var(--text-3); }

/* Sub Tabs */
.cv2-subtabs {
  display: flex; gap: 4px;
  padding: 14px 0 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 14px;
}
.cv2-subtab {
  position: relative;
  display: inline-flex; align-items: center; gap: 8px;
  padding: 9px 18px;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.18s;
}
.cv2-subtab:hover { color: var(--text); background: var(--surface-2); border-color: var(--border); }
.cv2-subtab.active {
  color: var(--primary); background: var(--surface);
  border-color: var(--border); border-bottom-color: var(--surface);
  margin-bottom: -1px;
}
.cv2-subtab-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--text-3); transition: all 0.2s;
}
.cv2-subtab.active .cv2-subtab-dot {
  background: var(--primary);
  box-shadow: 0 0 0 3px rgba(37,99,235,0.18);
}
.cv2-subtab-hint {
  font-size: 11px; font-weight: 400; color: var(--text-3);
}
.cv2-subtab.active .cv2-subtab-hint { color: var(--primary); opacity: 0.7; }

/* Toolbar */
.cv2-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 14px; gap: 12px;
}
.cv2-toolbar-left { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.cv2-toolbar-right { display: flex; gap: 8px; }
.cv2-search-wrap { position: relative; }
.cv2-search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); font-size: 13px; }
.cv2-input {
  height: 36px; background: #e2e8f0; border: 1px solid rgba(241,245,249,0.6);
  border-radius: 8px; padding: 0 12px; font-size: 13px; color: #1e293b; outline: none;
  font-family: inherit;
}
.cv2-input::placeholder { color: #475569; }
.cv2-input:focus { border-color: rgba(37,99,235,0.5); background: rgba(37,99,235,0.05); }
.cv2-search-wrap .cv2-input { padding-left: 32px; width: 220px; }
.cv2-conf-wrap {
  display: flex; align-items: center; gap: 6px;
  height: 36px; padding: 0 10px;
  background: rgba(15,23,42,0.04); border: 1px solid rgba(15,23,42,0.08);
  border-radius: 8px;
}
.cv2-conf-label { font-size: 12px; color: var(--text-3); }
.cv2-conf-input {
  width: 56px; height: 24px;
  background: transparent; border: none; outline: none;
  font-size: 13px; font-weight: 600; color: var(--primary);
  font-family: 'Courier New', monospace;
}

/* Buttons */
.cv2-btn {
  height: 36px; padding: 0 16px; border-radius: 8px; font-size: 13px;
  font-weight: 500; cursor: pointer; border: none; transition: all 0.15s;
  font-family: inherit;
}
.cv2-btn-cyan { background: rgba(37,99,235,0.1); color: var(--primary); border: 1px solid rgba(37,99,235,0.2); }
.cv2-btn-cyan:hover { background: rgba(37,99,235,0.2); }
.cv2-btn-red { background: rgba(248,113,113,0.1); color: var(--status-alert); border: 1px solid rgba(248,113,113,0.2); }
.cv2-btn-red:hover { background: rgba(248,113,113,0.2); }
.cv2-btn-red:disabled { opacity: 0.4; cursor: not-allowed; }

/* Help */
.cv2-help {
  background: rgba(241,245,249,0.8); border: 1px solid rgba(37,99,235,0.12);
  border-radius: 10px; padding: 16px 20px; margin-bottom: 12px;
}
.cv2-help-title { font-size: 13px; font-weight: 700; color: var(--primary); margin-bottom: 14px; }
.cv2-help-grid {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  gap: 12px 24px;
}
.cv2-help-item { display: flex; gap: 10px; font-size: 11.5px; line-height: 1.7; }
.cv2-help-key { color: var(--primary); font-weight: 600; white-space: nowrap; min-width: 80px; }
.cv2-help-val { color: var(--text-3); }
.cv2-help-val code {
  font-family: 'Courier New', monospace; font-size: 10px;
  color: var(--primary); background: rgba(37,99,235,0.08);
  border-radius: 3px; padding: 1px 4px; font-weight: 500;
}
.cv2-help-val strong { color: #1e293b; font-weight: 600; }

/* Card / Table */
.cv2-card {
  background: rgba(15, 23, 42, 0.03); border: 1px solid #e2e8f0;
  border-radius: 12px; overflow: hidden;
}
.table-scroll { overflow-x: auto; }
.cv2-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cv2-table th {
  padding: 11px 14px; text-align: left; font-weight: 600; font-size: 11px;
  color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em;
  background: rgba(15, 23, 42, 0.04); border-bottom: 1px solid #e2e8f0;
  white-space: nowrap;
}
.cv2-table td { padding: 10px 14px; border-bottom: 1px solid rgba(15,23,42,0.04); vertical-align: middle; }
.cv2-row:hover td { background: rgba(37,99,235,0.03); }
.cv2-empty { text-align: center; color: #475569; padding: 36px !important; font-size: 13px; }

/* Taxonomy table */
.cv2-l1-tag {
  display: inline-block; min-width: 28px; padding: 2px 8px;
  background: var(--primary); color: white;
  border-radius: 4px; font-size: 11px; font-weight: 700;
  text-align: center; font-family: 'Courier New', monospace;
}
.cv2-code-text {
  font-family: 'Courier New', monospace; font-size: 12px;
  color: var(--text-2);
}
.cv2-l3-code { color: var(--primary); font-weight: 600; }
.cv2-gb { color: var(--status-ok); font-weight: 600; }
.cv2-quota {
  display: inline-block; padding: 1px 7px;
  background: rgba(37,99,235,0.08); color: var(--primary);
  border-radius: 3px; font-size: 11px; font-weight: 600;
  font-family: 'Courier New', monospace;
}
.cv2-name-stack { display: flex; flex-direction: column; gap: 1px; }
.cv2-name-l1 { font-size: 11px; color: var(--text-3); }
.cv2-name-l3 { font-size: 13px; font-weight: 600; color: #1e293b; }
.cv2-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.cv2-tag {
  display: inline-block; padding: 1px 7px; border-radius: 3px;
  font-size: 11px; font-weight: 600;
}
.tag-part-基础 { background: rgba(99,102,241,0.1); color: #6366f1; }
.tag-part-主体 { background: rgba(37,99,235,0.1); color: var(--primary); }
.tag-part-装饰 { background: rgba(236,72,153,0.1); color: #ec4899; }
.tag-part-屋面 { background: rgba(245,158,11,0.1); color: #f59e0b; }
.tag-part-其他 { background: rgba(15,23,42,0.06); color: var(--text-3); }

.cv2-main-aux {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600;
}
.ma-主材 { background: rgba(34,197,94,0.12); color: #16a34a; }
.ma-辅材 { background: rgba(148,163,184,0.15); color: #475569; }
.cv2-unit {
  font-family: 'Courier New', monospace; font-size: 12px;
  font-weight: 600; color: var(--text-2);
}
.cv2-std-text {
  font-family: 'Courier New', monospace; font-size: 11px;
  color: var(--text-3); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; max-width: 130px;
}

/* Breed map table */
.cv2-breed-text { color: #1e293b; font-weight: 600; font-size: 13px; }
.cv2-src {
  display: inline-block; padding: 2px 9px; border-radius: 5px;
  font-size: 11px; font-weight: 600;
}
.src-v1_translated { background: rgba(37,99,235,0.1); color: var(--primary); }
.src-ai_v2 { background: rgba(251,191,36,0.1); color: var(--status-warn); }
.src-manual { background: rgba(52,211,153,0.1); color: var(--status-ok); }
.cv2-conf { font-weight: 700; font-size: 12px; font-family: 'Courier New', monospace; }
.conf-high { color: var(--status-ok); }
.conf-mid  { color: var(--status-warn); }
.conf-low  { color: var(--status-alert); }
.cv2-date { color: var(--text-3); font-size: 12px; white-space: nowrap; font-family: 'Courier New', monospace; }

/* Transition */
.cv2-slide-enter-active, .cv2-slide-leave-active { transition: all 0.2s ease; overflow: hidden; }
.cv2-slide-enter-from, .cv2-slide-leave-to { opacity: 0; transform: translateY(-6px); }
</style>
