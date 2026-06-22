<template>
  <div class="sync-page">
    <!-- Page Header -->
    <PageHeader
      variant="flat"
      title="数据同步"
      subtitle="9 城市材料价格抓取 / ODS → DWD → DWS 清洗链路 / 进度监控与运行状况"
      :stats="[
        { label: '同步城市', value: stats.cities },
        {
          label: `入库文档${stats.odsDelta > 0 ? ` <span class='delta'>+${stats.odsDelta} / 7d</span>` : ''}`,
          value: stats.odsDocs.toLocaleString(),
          title: 'ODS 索引实际文档数 = sum(ods.*.count)',
        },
        {
          label: '清洗记录',
          value: stats.dwsRecords.toLocaleString(),
          title: 'DWS 索引实际记录数 = sum(dws.*.count)',
        },
        {
          label: '清洗完成率',
          value: stats.cleanRate + '%',
          tone: stats.cleanRate === '0.0' ? 'warn' : 'ok',
          title: '清洗完成率 = DWS / ODS',
        },
      ]"
    ><template #icon>🔄</template></PageHeader>

    <div class="sync-subtabs">
      <button class="sync-subtab" :class="{ active: subTab === 'clean' }" @click="subTab = 'clean'">
        <span class="sync-subtab-dot"></span>
        数据清洗
        <span class="sync-subtab-hint">ODS → DWD → DWS 链路</span>
      </button>
      <button class="sync-subtab" :class="{ active: subTab === 'scrape' }" @click="subTab = 'scrape'">
        <span class="sync-subtab-dot"></span>
        抓取任务
        <span class="sync-subtab-hint">各城市 ODS 抓取进度</span>
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
import PageHeader from './PageHeader.vue'

const API = import.meta.env.VITE_API_URL || '/api'
const subTab = ref('clean')

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

/* Header（已迁移至 PageHeader flat 变体） */
.sync-page :deep(.delta) {
  display: inline-block; margin-left: 4px; padding: 1px 5px;
  background: rgba(34,197,94,0.12); color: #16a34a;
  border-radius: 3px; font-size: 9px; font-weight: 600;
}

.sync-subtabs {
  display: flex;
  gap: 4px;
  padding: 14px 20px 2px;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
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
