<template>
  <!-- Toolbar -->
  <div class="ctx-toolbar">
    <div class="ctx-search-wrap">
      <span class="ctx-search-icon">🔍</span>
      <input
        class="ctx-input"
        v-model="mapKeyword"
        placeholder="搜索品种名..."
        @input="debounceLoadMap(1)"
      />
    </div>
  </div>

  <!-- Table -->
  <div class="ctx-card">
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th style="width:50%" class="text-left no-sort">品种</th>
            <th style="width:90px" class="no-sort">L3</th>
            <th class="text-left no-sort">L3 名称</th>
            <th style="width:90px" class="no-sort">来源</th>
            <th style="width:80px" class="no-sort">置信度</th>
            <th style="width:140px" class="no-sort">更新时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="mapLoading">
            <td colspan="6" class="ctx-empty">加载中...</td>
          </tr>
          <tr v-else-if="!mapRows.length">
            <td colspan="6" class="ctx-empty">
              <div class="ctx-empty-art">🗂️</div>
              <div class="ctx-empty-title">暂无映射条目</div>
              <div class="ctx-empty-hint">试试调整筛选条件或清空全部</div>
              <button class="ctx-btn ctx-btn-cyan" @click="clearMapFilters" style="margin-top:12px">🔍 清空筛选</button>
            </td>
          </tr>
          <tr v-for="r in mapRows" :key="r.breed_clean" class="ctx-row" v-show="!mapLoading && mapRows.length">
            <td class="text-left"><span class="ctx-breed-text">{{ r.breed_clean }}</span></td>
            <td><span class="ctx-code-text ctx-l3-code">{{ r.l3 }}</span></td>
            <td class="text-left no-ellipsis">
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
      :page-size="mapPageSize"
      :page-size-options="mapPageSizeOptions"
      show-size-changer
      info-template="第 {from}-{to} 条 / 共 {total} 条"
      @change="loadMap"
      @update:page-size="mapPageSize = $event; loadMap(1)"
    />
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import axios from 'axios'
// import CustomSelect from './CustomSelect.vue' — unused filters removed
import AppPagination from './AppPagination.vue'

const props = defineProps({
  initialL3Filter: { type: String, default: '' }
})

const API = import.meta.env.VITE_API_URL || '/api'

// ── 状态 ──
const mapKeyword = ref('')
const mapPageSize = ref(50)
const mapPageSizeOptions = [50, 100, 200]
// mapL3Options / mapSourceOptions removed - unused
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
    const params = { page: p, page_size: mapPageSize.value }
    if (mapKeyword.value.trim()) params.keyword = mapKeyword.value.trim()
    const { data } = await axios.get(`${API}/stats/category-v2-breed-map`, { params })
    mapRows.value = data.rows || []
    mapTotal.value = data.total || 0
    mapPage.value = p
    // filter options removed — unused
  } catch (e) { console.error(e) }
  finally { mapLoading.value = false }
}

function clearMapFilters() {
  mapKeyword.value = ''
  loadMap(1)
}

// 监听外部 prop 变化（父组件切 tab 时预填筛选）
watch(() => props.initialL3Filter, (v) => {
  if (v) {
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
.ctx-toolbar-right { display: flex; gap: 8px; align-items: center; }

/* Search bar */
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
.ctx-search-wrap .ctx-input { padding-left: 32px; width: 220px; }
.ctx-btn-cyan { background: rgba(37,99,235,0.1); color: var(--primary); border: 1px solid rgba(37,99,235,0.2); }
.ctx-btn-cyan:hover { background: rgba(37,99,235,0.2); }

/* Card / Table */
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
.table-scroll { overflow-x: auto; }
.ctx-row { cursor: pointer; }
.ctx-empty { text-align: center; color: var(--text-2, #475569); padding: 48px 36px !important; }
.ctx-empty-art { font-size: 48px; opacity: 0.6; margin-bottom: 12px; }
.ctx-empty-title { font-size: 14px; font-weight: 600; color: var(--text, #0f172a); margin-bottom: 6px; }
.ctx-empty-hint { font-size: 12px; color: var(--text-3, #94a3b8); }

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