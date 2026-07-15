<template>
  <div class="ctx-page">
    <!-- Header -->
    <PageHeader
      variant="flat"
      title="分类体系"
      subtitle="3 级分类法（L1 / L2 / L3）+ 品种→L3 映射规则，数据源 <code>breed_canonical.db</code>（GB 50500 系列）"
      :stats="[
        { label: '一级', value: stats.taxonomy.l1 || 0 },
        { label: '三级分类', value: stats.taxonomy.l3 || 0 },
        { label: '品种映射', value: fmt.int(stats.map.total) },
        {
          label: 'L3 命中率',
          value: hitRate + '%',
          tone: 'ok',
          title: `L3 命中率：${stats.map.l3_in_taxonomy} / ${stats.map.l3_in_taxonomy + stats.map.l3_not_in_taxonomy}`,
        },
      ]"
    />

    <!-- Sub Tabs -->
    <div class="ctx-subtabs">
      <button class="ctx-subtab" :class="{ active: subTab === 'map' }" @click="subTab = 'map'">
        <span class="ctx-subtab-dot"></span>
        品种映射
      </button>
      <button class="ctx-subtab" :class="{ active: subTab === 'taxonomy' }" @click="subTab = 'taxonomy'">
        <span class="ctx-subtab-dot"></span>
        分类法
      </button>
    </div>

    <!-- 置信度分布卡片（仅品种映射 tab 显示） -->
    <div v-if="subTab === 'map' && confDist.ok" class="ctx-conf-cards">
      <div class="ctx-conf-card">
        <div class="ctx-conf-card-head">
          <span class="ctx-conf-card-label">总数</span>
          <span class="ctx-conf-card-value">{{ fmt.int(confDist.total) }}</span>
        </div>
        <div class="ctx-conf-card-bar">
          <div class="bar-seg high" :style="{ width: pct(confDist.buckets.high) + '%' }"></div>
          <div class="bar-seg mid"  :style="{ width: pct(confDist.buckets.mid)  + '%' }"></div>
          <div class="bar-seg low"  :style="{ width: pct(confDist.buckets.low)  + '%' }"></div>
        </div>
        <div class="ctx-conf-card-foot">
          <span class="foot-tag high">● 高 {{ fmt.int(confDist.buckets.high) }} ({{ pct(confDist.buckets.high) }}%)</span>
          <span class="foot-tag mid">● 中 {{ fmt.int(confDist.buckets.mid) }} ({{ pct(confDist.buckets.mid) }}%)</span>
          <span class="foot-tag low">● 低 {{ fmt.int(confDist.buckets.low) }} ({{ pct(confDist.buckets.low) }}%)</span>
        </div>
      </div>
      <div class="ctx-conf-source">
        <div class="ctx-conf-source-title">来源分布</div>
        <div v-for="row in confDist.by_source" :key="row.source" class="ctx-conf-source-row">
          <span class="ctx-src" :class="`ctx-src-${row.source}`">{{ sourceLabel(row.source) }}</span>
          <span class="ctx-conf-source-count">{{ fmt.int(row.count) }}</span>
          <span class="ctx-conf-source-pct">{{ pct(row.count) }}%</span>
          <span class="ctx-conf-source-bar" :style="{ width: pct(row.count) + '%' }"></span>
        </div>
      </div>
      <div class="ctx-conf-meta">
        <div class="ctx-conf-meta-title">时间范围</div>
        <div class="ctx-conf-meta-line">
          <code>{{ dateFrom || '*' }}</code> → <code>{{ dateTo || '*' }}</code>
          <span v-if="!dateFrom && !dateTo" class="ctx-conf-meta-note">(全部历史)</span>
        </div>
        <div class="ctx-conf-meta-line ctx-conf-meta-stats">
          <span>命中 L1：{{ confDist.by_l1.length }} 个大类</span>
          <span>·</span>
          <span>已加载到表格</span>
        </div>
      </div>
    </div>

    <!-- 子组件 -->
    <CategoryTaxonomyTab
      v-if="subTab === 'taxonomy'"
      @jump-to-breed-map="handleJumpToBreedMap"
    />
    <BreedMapTab
      v-else-if="subTab === 'map'"
      :initial-l3-filter="mapInitialL3Filter"
      :date-from="dateFrom"
      :date-to="dateTo"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import CategoryTaxonomyTab from './CategoryTaxonomyTab.vue'
import BreedMapTab from './BreedMapTab.vue'
import PageHeader from './PageHeader.vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'

const API = import.meta.env.VITE_API_URL || '/api'
const fmt = useFormatNumber()
const route = useRoute()

// 顶层统计
const stats = ref({
  taxonomy: { l1: 0, l2: 0, l3: 0 },
  map: { total: 0, l3_in_taxonomy: 0, l3_not_in_taxonomy: 0 },
})

// 置信度分布
const confDist = ref({
  ok: false,
  total: 0,
  buckets: { high: 0, mid: 0, low: 0 },
  by_source: [],
  by_l1: [],
})

const hitRate = computed(() => {
  const inT = stats.value.map.l3_in_taxonomy
  const out = stats.value.map.l3_not_in_taxonomy
  const tot = inT + out
  if (!tot) return '0.0'
  return fmt.pct((inT / tot) * 100)
})

// Tab 状态
const subTab = ref('map')
const mapInitialL3Filter = ref('')
const dateFrom = ref('')
const dateTo   = ref('')

// 来源 label（共享给 cards + 子组件保持一致）
const srcLabels = {
  v1_translated: '翻译',
  ai_v2: 'AI v2',
  manual: '手动',
  etl_v3_sqlite: 'v3 ETL',
  ai_dify: 'AI · Dify',
}
function sourceLabel(s) { return srcLabels[s] || s || '—' }

function pct(v) {
  const total = confDist.value.total
  if (!total) return '0.0'
  return ((v / total) * 100).toFixed(1)
}

async function loadStats() {
  try {
    const { data } = await axios.get(`${API}/stats/category-v2-stats`)
    if (data.ok) stats.value = data
  } catch (e) { console.error(e) }
}

async function loadConfDist() {
  try {
    const params = {}
    if (dateFrom.value) params.date_from = dateFrom.value
    if (dateTo.value)   params.date_to   = dateTo.value
    const { data } = await axios.get(`${API}/stats/category-v2-confidence-dist`, { params })
    confDist.value = data
  } catch (e) { console.error(e) }
}

// 从 URL 读 date_from/date_to
function readUrlDates() {
  dateFrom.value = String(route.query.date_from || '')
  dateTo.value   = String(route.query.date_to   || '')
}
watch(() => route.query, () => {
  readUrlDates()
  if (subTab.value === 'map') loadConfDist()
}, { deep: true })

function handleJumpToBreedMap(l3) {
  subTab.value = 'map'
  mapInitialL3Filter.value = l3
}

watch(subTab, (v) => {
  if (v === 'map') loadConfDist()
})

onMounted(() => {
  readUrlDates()
  loadStats()
  loadConfDist()
})
</script>

<style scoped>
.ctx-page { padding: 0 28px 64px; }

.ctx-subtitle code,
.ctx-page :deep(.page-header-subtitle code) {
  font-family: 'Courier New', monospace; font-size: 10px;
  color: var(--primary); background: rgba(37,99,235,0.08);
  border-radius: 3px; padding: 1px 4px; font-weight: 500;
}

/* Conf dist cards */
.ctx-conf-cards {
  display: grid;
  grid-template-columns: 1.4fr 1fr 0.8fr;
  gap: 14px;
  margin: 16px 0;
}
.ctx-conf-card,
.ctx-conf-source,
.ctx-conf-meta {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: var(--shadow);
}
.ctx-conf-card-head {
  display: flex; align-items: baseline; justify-content: space-between;
  margin-bottom: 10px;
}
.ctx-conf-card-label { font-size: 12px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; }
.ctx-conf-card-value { font-size: 24px; font-weight: 700; color: var(--text); font-family: 'Courier New', monospace; }
.ctx-conf-card-bar {
  display: flex; height: 8px; border-radius: 4px; overflow: hidden;
  background: var(--surface-3, #e2e8f0);
  margin-bottom: 10px;
}
.ctx-conf-card-bar .bar-seg.high { background: var(--status-ok); }
.ctx-conf-card-bar .bar-seg.mid  { background: var(--status-warn); }
.ctx-conf-card-bar .bar-seg.low  { background: var(--status-alert); }
.ctx-conf-card-foot { display: flex; gap: 12px; flex-wrap: wrap; font-size: 11.5px; }
.foot-tag { font-weight: 600; }
.foot-tag.high { color: var(--status-ok); }
.foot-tag.mid  { color: var(--status-warn); }
.foot-tag.low  { color: var(--status-alert); }

.ctx-conf-source-title,
.ctx-conf-meta-title {
  font-size: 12px; font-weight: 600; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.05em;
  margin-bottom: 8px;
}
.ctx-conf-source-row {
  position: relative;
  display: grid;
  grid-template-columns: auto auto 48px 1fr;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  font-size: 12px;
}
.ctx-conf-source-count {
  font-weight: 700; font-family: 'Courier New', monospace; color: var(--text);
  text-align: right;
}
.ctx-conf-source-pct {
  font-size: 11px; color: var(--text-3); font-family: 'Courier New', monospace;
  text-align: right;
}
.ctx-conf-source-row::before {
  content: '';
  position: absolute;
  left: 0; right: 56px;
  top: 50%;
  height: 4px;
  background: var(--surface-3, #e2e8f0);
  border-radius: 2px;
  z-index: 0;
  opacity: 0.55;
}
.ctx-conf-source-bar {
  display: block;
  height: 4px;
  background: var(--primary);
  border-radius: 2px;
  z-index: 1;
  min-width: 2px;
}

.ctx-conf-meta-line {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-2);
  font-family: 'Courier New', monospace;
}
.ctx-conf-meta-line code {
  background: rgba(37,99,235,0.1);
  color: var(--primary);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.ctx-conf-meta-note { font-family: inherit; font-size: 11px; color: var(--text-3); }
.ctx-conf-meta-stats { color: var(--text-3); margin-top: 6px; gap: 8px; }

/* Source tags（share with BreedMapTab via :global） */
.ctx-conf-source :deep(.ctx-src-etl_v3_sqlite) { background: rgba(99,102,241,0.12); color: #6366f1; padding: 2px 9px; border-radius: 5px; font-size: 11px; font-weight: 600; display: inline-block; }
.ctx-conf-source :deep(.ctx-src-ai_dify)       { background: rgba(168,85,247,0.12); color: #a855f7; padding: 2px 9px; border-radius: 5px; font-size: 11px; font-weight: 600; display: inline-block; }
.ctx-conf-source :deep(.ctx-src-manual)        { background: rgba(52,211,153,0.1); color: var(--status-ok); padding: 2px 9px; border-radius: 5px; font-size: 11px; font-weight: 600; display: inline-block; }
.ctx-conf-source :deep(.ctx-src-v1_translated) { background: rgba(37,99,235,0.1); color: var(--primary); padding: 2px 9px; border-radius: 5px; font-size: 11px; font-weight: 600; display: inline-block; }
.ctx-conf-source :deep(.ctx-src-ai_v2)         { background: rgba(251,191,36,0.1); color: var(--status-warn); padding: 2px 9px; border-radius: 5px; font-size: 11px; font-weight: 600; display: inline-block; }

/* Sub Tabs */
.ctx-subtabs {
  display: flex; gap: 4px;
  padding: 14px 0 0;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
  z-index: 100;
  padding-bottom: 2px;
}
.ctx-subtab {
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
.ctx-subtab:hover { color: var(--text); background: var(--surface-2); border-color: var(--border); }
.ctx-subtab.active {
  color: var(--primary); background: var(--surface);
  border-color: var(--border); border-bottom-color: var(--surface);
  margin-bottom: -1px;
}
.ctx-subtab-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--text-3); transition: all 0.2s;
}
.ctx-subtab.active .ctx-subtab-dot {
  background: var(--primary);
  box-shadow: 0 0 0 3px rgba(37,99,235,0.18);
}
.ctx-subtab-hint {
  font-size: 11px; font-weight: 400; color: var(--text-3);
  margin-left: 4px;
}
.ctx-subtab.active .ctx-subtab-hint { color: var(--primary); opacity: 0.85; }
</style>
