<template>
  <div class="sync-page">
    <!-- Page Header -->
    <PageHeader
      variant="flat"
      title="数据同步"
      :subtitle="`${stats.cities} 城市材料价格抓取 / ODS → DWD → DWS 清洗链路 / 进度监控与运行状况`"
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

    <!-- 重庆「最近检查」卡片（凌晨 1 点 cron check.py 写入 chongqing_price_check_log） -->
    <div v-if="checkLatest && checkLatest.status !== 'no_record'" class="check-card" :class="`check-status-${checkLatest.status}`">
      <div class="check-card-head">
        <span class="check-card-icon">⏰</span>
        <span class="check-card-title">重庆最近检查</span>
        <span class="check-card-time">{{ checkLatest.run_at }}</span>
        <span class="check-card-badge">{{ statusLabel(checkLatest.status) }}</span>
      </div>
      <div class="check-card-body">
        <div class="check-cell">
          <div class="check-cell-label">源站最新</div>
          <div class="check-cell-val">{{ checkLatest.site_latest_period || '—' }}</div>
          <div class="check-cell-sub">{{ checkLatest.site_latest_year }}年 {{ checkLatest.site_latest_month }}</div>
        </div>
        <div class="check-vs">vs</div>
        <div class="check-cell">
          <div class="check-cell-label">ES 最新</div>
          <div class="check-cell-val">{{ checkLatest.es_latest_period || '—' }}</div>
          <div class="check-cell-sub">入库 {{ (checkLatest.es_latest_create_time || '').slice(0, 19) }}</div>
        </div>
        <div class="check-msg">{{ checkLatest.message }}</div>
      </div>
    </div>
    <div v-else-if="checkLatest && checkLatest.status === 'no_record'" class="check-card check-status-empty">
      <span class="check-card-icon">⏰</span>
      重庆增量检测尚无记录（check.py 还没跑过）
    </div>

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

// ── 重庆最近检查（check.py → chongqing_price_check_log）──
const checkLatest = ref(null)
function statusLabel(s) {
  return {
    ok: '✅ 无新数据',
    new_data: '🔔 有更新',
    no_es_data: '⚠️ ES 无数据',
    no_site_data: '⚠️ 源站无数据',
    no_record: '尚无记录',
  }[s] || s
}
async function loadCheckLatest() {
  try {
    const { data } = await axios.get(`${API}/stats/chongqing-check-latest`)
    checkLatest.value = data
  } catch (e) { console.error(e) }
}

onMounted(() => { loadStats(); loadCheckLatest() })
</script>

<style scoped>
/* ── 重庆「最近检查」卡片 ── */
.check-card {
  margin: 14px 20px 0;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--text-3);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 12px;
  display: flex; flex-direction: column; gap: 10px;
}
.check-card-icon { font-size: 14px; }
.check-card-title { font-weight: 600; }
.check-card-time { color: var(--text-3); margin-left: auto; font-family: ui-monospace, monospace; }
.check-card-badge {
  padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 600;
  background: var(--surface-2); color: var(--text-2);
}
.check-card-body {
  display: flex; align-items: center; gap: 16px; padding-top: 8px;
  border-top: 1px dashed var(--border);
}
.check-cell { display: flex; flex-direction: column; gap: 2px; min-width: 140px; }
.check-cell-label { color: var(--text-3); font-size: 10px; }
.check-cell-val { font-size: 14px; font-weight: 600; font-family: ui-monospace, monospace; }
.check-cell-sub { color: var(--text-3); font-size: 10px; }
.check-vs { color: var(--text-3); font-weight: 600; }
.check-msg { margin-left: auto; color: var(--text-2); font-size: 12px; max-width: 40%; }

.check-status-ok { border-left-color: #16a34a; }
.check-status-ok .check-card-badge { background: rgba(34,197,94,0.15); color: #16a34a; }

.check-status-new_data { border-left-color: #ea580c; }
.check-status-new_data .check-card-badge { background: rgba(234,88,12,0.15); color: #ea580c; }

.check-status-no_es_data { border-left-color: #dc2626; }
.check-status-no_es_data .check-card-badge { background: rgba(220,38,38,0.15); color: #dc2626; }

.check-status-no_site_data { border-left-color: #6b7280; }
.check-status-no_site_data .check-card-badge { background: rgba(107,114,128,0.15); color: #6b7280; }

.check-status-empty { color: var(--text-3); font-style: italic; }

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
