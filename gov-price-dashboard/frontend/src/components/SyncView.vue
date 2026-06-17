<template>
  <div class="sync-page">
    <!-- Page Header（跟 CategoryTaxonomyView 的 .ctx-header 同构） -->
    <div class="sync-header">
      <div class="sync-header-left">
        <div class="sync-title">🔄 数据同步</div>
        <div class="sync-subtitle">
          8 城市材料价格抓取 / ODS → DWD → DWS 清洗链路 / 进度监控与运行状况
        </div>
      </div>
      <div class="sync-header-stats">
        <div class="sync-stat">
          <span class="sync-stat-val">{{ stats.cities }}</span>
          <span class="sync-stat-key">同步城市</span>
        </div>
        <div class="sync-stat" :title="`ODS 索引实际文档数 = sum(ods.*.count)`">
          <span class="sync-stat-val">{{ stats.odsDocs.toLocaleString() }}</span>
          <span class="sync-stat-key">入库文档 <span v-if="stats.odsDelta > 0" class="sync-stat-delta">+{{ stats.odsDelta }} / 7d</span></span>
        </div>
        <div class="sync-stat" :title="`DWS 索引实际记录数 = sum(dws.*.count)`">
          <span class="sync-stat-val">{{ stats.dwsRecords.toLocaleString() }}</span>
          <span class="sync-stat-key">清洗记录</span>
        </div>
        <div class="sync-stat" :title="`清洗完成率 = DWS / ODS`">
          <span class="sync-stat-val" :class="{ 'sync-stat-rate': stats.cleanRate !== '0.0', 'sync-stat-warn': stats.cleanRate === '0.0' }">
            {{ stats.cleanRate }}%
          </span>
          <span class="sync-stat-key">清洗完成率</span>
        </div>
      </div>
    </div>

    <div class="sync-subtabs">
      <button class="sync-subtab" :class="{ active: subTab === 'scrape' }" @click="subTab = 'scrape'">
        <span class="sync-subtab-dot"></span>
        抓取任务
        <span class="sync-subtab-hint">各城市 ODS 抓取进度</span>
      </button>
      <button class="sync-subtab" :class="{ active: subTab === 'clean' }" @click="subTab = 'clean'">
        <span class="sync-subtab-dot"></span>
        数据清洗
        <span class="sync-subtab-hint">ODS → DWD → DWS 链路</span>
      </button>
      <button class="sync-subtab" :class="{ active: subTab === 'cleandim' }" @click="subTab = 'cleandim'">
        <span class="sync-subtab-dot"></span>
        维度清洗
        <span class="sync-subtab-hint">一级分类 × 规格型号 × 城市覆盖</span>
      </button>
    </div>

    <ScrapeView v-if="subTab === 'scrape'" />
    <DataProvenanceView v-else-if="subTab === 'clean'" />
    <CleanDimView v-else-if="subTab === 'cleandim'" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import ScrapeView from './ScrapeView.vue'
import DataProvenanceView from './DataProvenanceView.vue'
import CleanDimView from './CleanDimView.vue'

const API = import.meta.env.VITE_API_URL || '/api'
const subTab = ref('scrape')

// ── 顶部 stats（与 CategoryTaxonomyView 的 .ctx-header-stats 同构）──
// 数据源：/api/stats/provenance（ODS / DWD / DWS 三层索引的 count）
// 之前用 /api/stats/scrape-progress-all 错拿的是“抓取进度”索引的 total_docs，
// 跟实际入库的 ODS 索引差 ~17K，不准确。
const stats = ref({
  cities: 0,
  odsDocs: 0,    // 实际入库文档（ODS 索引 count）
  dwsRecords: 0, // 实际清洗后记录（DWS 索引 count）
  cleanRate: '0.0', // 清洗完成率 = DWS / ODS
  odsDelta: 0,   // ODS 较昨日新增量（来自 provenance 顶层 recent_7d）
})

async function loadStats() {
  try {
    // 1. 顶层 stats（各城 ODS 总量、过去 7 天趋势）
    const { data: prov } = await axios.get(`${API}/stats/provenance`)
    const allCities = prov?.all_cities || {}
    const cities = Object.keys(allCities).length
    const odsDocs = Object.values(allCities)
      .reduce((s, c) => s + Number(c?.ods?.count || 0), 0)
    const dwsRecords = Object.values(allCities)
      .reduce((s, c) => s + Number(c?.dws?.count || 0), 0)
    const cleanRate = odsDocs > 0
      ? ((dwsRecords / odsDocs) * 100).toFixed(1)
      : '0.0'
    // 7 天新增文档量（top-level total / recent_7d / prev_7d 在 provenance 已有）
    const total = Number(prov?.total || 0)
    const recent7d = Number(prov?.recent_7d || 0)

    stats.value = {
      cities,
      odsDocs,
      dwsRecords,
      cleanRate,
      odsDelta: recent7d,
    }
  } catch (e) { console.error(e) }
}

onMounted(loadStats)
</script>

<style scoped>
.sync-page {
  padding: 0 28px 28px;
  min-height: 100vh;
  color: var(--text);
}

/* Header（跟 CategoryTaxonomyView 的 .ctx-header 同构） */
.sync-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 22px 0 16px;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 16px;
}
.sync-title { font-size: 18px; font-weight: 700; color: #1e293b; }
.sync-subtitle { font-size: 12px; color: var(--text-3); margin-top: 3px; line-height: 1.6; }
.sync-header-stats { display: flex; gap: 20px; }
.sync-stat { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.sync-stat-val { font-size: 18px; font-weight: 700; color: var(--primary); }
.sync-stat-rate { color: var(--status-ok); }
.sync-stat-warn { color: var(--status-warn, #ea580c); }
.sync-stat-delta {
  display: inline-block; margin-left: 4px; padding: 1px 5px;
  background: rgba(34,197,94,0.12); color: #16a34a;
  border-radius: 3px; font-size: 9px; font-weight: 600;
}
.sync-stat-key { font-size: 11px; color: var(--text-3); display: flex; align-items: center; gap: 4px; }

.sync-subtabs {
  display: flex;
  gap: 4px;
  padding: 14px 20px 2px;
  border-bottom: 1px solid var(--border);
  /* 粘性定位：跟顶栏下方吸顶（跟 CategoryTaxonomyView 的 .ctx-subtabs 一致） */
  position: sticky;
  top: var(--topbar-h, 60px);
  background: var(--bg);
  z-index: 100;
}

.sync-subtab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
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

.sync-subtab:hover {
  color: var(--text);
  background: var(--surface-2);
  border-color: var(--border);
}

.sync-subtab.active {
  color: var(--primary);
  background: var(--surface);
  border-color: var(--border);
  border-bottom-color: var(--surface);
  margin-bottom: -1px;
}

.sync-subtab-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
  transition: all 0.2s;
}
.sync-subtab.active .sync-subtab-dot {
  background: var(--primary);
  box-shadow: 0 0 0 3px rgba(37,99,235,0.18);
}

.sync-subtab-hint {
  font-size: 11px;
  color: var(--text-3);
  font-weight: 400;
  margin-left: 4px;
}
.sync-subtab.active .sync-subtab-hint {
  color: var(--primary-light, var(--primary));
}
</style>
