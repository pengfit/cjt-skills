<template>
  <!-- Toolbar -->
  <div class="ctx-toolbar">
    <div class="ctx-toolbar-left">
      <div class="ctx-search-wrap">
        <span class="ctx-search-icon">🔍</span>
        <input
          class="ctx-input"
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
      <div class="ctx-conf-wrap">
        <span class="ctx-conf-label">置信度 ≥</span>
        <input
          class="ctx-conf-input"
          type="number"
          step="0.05"
          min="0"
          max="1"
          v-model.number="mapMinConf"
          @change="loadMap(1)"
        />
      </div>
    </div>
    <div class="ctx-toolbar-right">
      <button class="ctx-btn ctx-btn-red" @click="clearMapFilters" :disabled="mapLoading">
        🗑️ 清空筛选
      </button>
    </div>
  </div>

  <!-- Table -->
  <div class="ctx-card">
    <div class="table-scroll">
      <table class="ctx-table">
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
            <td colspan="6" class="ctx-empty">加载中...</td>
          </tr>
          <tr v-else-if="!mapRows.length">
            <td colspan="6" class="ctx-empty">暂无映射</td>
          </tr>
          <tr v-for="r in mapRows" :key="r.breed_clean" class="ctx-row" v-show="!mapLoading && mapRows.length">
            <td><span class="ctx-breed-text">{{ r.breed_clean }}</span></td>
            <td><span class="ctx-code-text ctx-l3-code">{{ r.l3 }}</span></td>
            <td>
              <div class="ctx-name-stack">
                <span class="ctx-name-l1">{{ r.name_l1 || '—' }}</span>
                <span class="ctx-name-l3">{{ r.name_l3 || '—' }}</span>
              </div>
            </td>
            <td>
              <span class="ctx-src" :class="`ctx-src-${r.source}`">{{ sourceLabel(r.source) }}</span>
            </td>
            <td>
              <span class="ctx-conf" :class="confClass(r.confidence)">
                {{ (r.confidence ?? 1).toFixed(2) }}
              </span>
            </td>
            <td class="ctx-date">{{ formatDate(r.updated_at) }}</td>
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

<script setup>
import { ref, watch, onMounted } from 'vue'
import axios from 'axios'
import CustomSelect from './CustomSelect.vue'
import AppPagination from './AppPagination.vue'

const props = defineProps({
  initialL3Filter: { type: String, default: '' }
})

const API = import.meta.env.VITE_API_URL || '/api'

// ── 状态 ──
const mapKeyword = ref('')
const mapL3Filter = ref(props.initialL3Filter || '')
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
  v1_translated: '翻译',
  ai_v2: 'AI',
  manual: '手动',
}
function sourceLabel(s) { return srcLabels[s] || s }
function confClass(c) {
  if (c == null || c >= 0.85) return 'ctx-conf-high'
  if (c >= 0.7) return 'ctx-conf-mid'
  return 'ctx-conf-low'
}
function formatDate(s) {
  if (!s) return '—'
  return String(s).slice(0, 19).replace('T', ' ')
}

function debounceLoadMap(p) {
  clearTimeout(window._ctx_map_debounce)
  window._ctx_map_debounce = setTimeout(() => loadMap(p || 1), 300)
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

function clearMapFilters() {
  mapKeyword.value = ''
  mapL3Filter.value = ''
  mapSourceFilter.value = ''
  mapMinConf.value = 0
  loadMap(1)
}

// 监听外部 prop 变化（父组件切 tab 时预填筛选）
watch(() => props.initialL3Filter, (v) => {
  if (v && v !== mapL3Filter.value) {
    mapL3Filter.value = v
    loadMap(1)
  }
}, { immediate: false })

defineExpose({ loadMap, refresh: () => loadMap(mapPage.value) })

onMounted(() => {
  loadMap(1)
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
.ctx-conf-wrap {
  display: flex; align-items: center; gap: 6px;
  height: 36px; padding: 0 10px;
  background: rgba(15,23,42,0.04); border: 1px solid rgba(15,23,42,0.08);
  border-radius: 8px;
}
.ctx-conf-label { font-size: 12px; color: var(--text-3); }
.ctx-conf-input {
  width: 56px; height: 24px;
  background: transparent; border: none; outline: none;
  font-size: 13px; font-weight: 600; color: var(--primary);
  font-family: 'Courier New', monospace;
}

/* Buttons */
.ctx-btn {
  height: 36px; padding: 0 16px; border-radius: 8px; font-size: 13px;
  font-weight: 500; cursor: pointer; border: none; transition: all 0.15s;
  font-family: inherit;
}
.ctx-btn-red { background: rgba(248,113,113,0.1); color: var(--status-alert); border: 1px solid rgba(248,113,113,0.2); }
.ctx-btn-red:hover { background: rgba(248,113,113,0.2); }
.ctx-btn-red:disabled { opacity: 0.4; cursor: not-allowed; }

/* Card / Table */
.ctx-card {
  background: rgba(15, 23, 42, 0.03); border: 1px solid #e2e8f0;
  border-radius: 12px; overflow: hidden;
}
.table-scroll { overflow-x: auto; }
.ctx-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.ctx-table th {
  padding: 11px 14px; text-align: left; font-weight: 600; font-size: 11px;
  color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em;
  background: rgba(15, 23, 42, 0.04); border-bottom: 1px solid #e2e8f0;
  white-space: nowrap;
}
.ctx-table td { padding: 10px 14px; border-bottom: 1px solid rgba(15,23,42,0.04); vertical-align: middle; }
.ctx-row:hover td { background: rgba(37,99,235,0.07); }
.ctx-row:hover td:first-child { box-shadow: inset 3px 0 0 var(--primary); }
.ctx-empty { text-align: center; color: #475569; padding: 48px 36px !important; }

/* Breed map-specific */
.ctx-breed-text { color: #1e293b; font-weight: 600; font-size: 13px; }
.ctx-code-text {
  font-family: 'Courier New', monospace; font-size: 12px;
  color: var(--text-2);
}
.ctx-l3-code { color: var(--primary); font-weight: 600; }
.ctx-name-stack { display: flex; flex-direction: column; gap: 2px; padding-left: 10px; border-left: 2px solid rgba(37,99,235,0.18); }
.ctx-name-l1 { font-size: 11px; color: var(--text-3); font-family: 'Courier New', monospace; }
.ctx-name-l3 { font-size: 13px; font-weight: 600; color: #1e293b; line-height: 1.3; }
.ctx-src {
  display: inline-block; padding: 2px 9px; border-radius: 5px;
  font-size: 11px; font-weight: 600;
}
.ctx-src-v1_translated { background: rgba(37,99,235,0.1); color: var(--primary); }
.ctx-src-ai_v2 { background: rgba(251,191,36,0.1); color: var(--status-warn); }
.ctx-src-manual { background: rgba(52,211,153,0.1); color: var(--status-ok); }
.ctx-conf { font-weight: 700; font-size: 12px; font-family: 'Courier New', monospace; }
.ctx-conf-high { color: var(--status-ok); }
.ctx-conf-mid  { color: var(--status-warn); }
.ctx-conf-low  { color: var(--status-alert); }
.ctx-date { color: var(--text-3); font-size: 12px; white-space: nowrap; font-family: 'Courier New', monospace; }
</style>