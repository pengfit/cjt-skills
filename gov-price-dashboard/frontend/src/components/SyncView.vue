<template>
  <div class="admin-page">
    <!-- Page Header -->
    <PageHeader
      variant="flat"
      title="数据同步"
      :subtitle="`${stats.cities} 城市材料价格抓取 / ODS → DWD → DWS 清洗链路 / 进度监控与运行状况`"
      :stats="[
        { label: '同步城市', value: stats.cities },
        {
          label: `入库文档${stats.odsDelta > 0 ? ` <span class='delta'>+${stats.odsDelta} / 7d</span>` : ''}`,
          value: fmt.int(stats.odsDocs),
          title: 'ODS 索引实际文档数 = sum(ods.*.count)',
        },
        {
          label: '清洗记录',
          value: fmt.int(stats.dwsRecords),
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

    <!-- 2026-07-29 改造: 删 sync-subtabs(原单 tab 占位冗余),<ScrapeView /> 直挂 -->
    <ScrapeView />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import ScrapeView from './ScrapeView.vue'
import PageHeader from './PageHeader.vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'
import { useFetch } from '../composables/useFetch.js'  // 2026-07-28 Step 2 扩 SyncView

// 2026-07-28 Step 2:const API 已被 useFetch 取代(api 实例自带 baseURL + 鉴权)
const { fetch: fetchProvenance } = useFetch()
// D.2026-07-12 统一数字格式化
const fmt = useFormatNumber()

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
  // 2026-07-28 Step 2:用 useFetch 取代 axios.get(自带 loading/error/鉴权)
  const prov = await fetchProvenance('/stats/provenance')
  if (!prov) return  // 错误已由 useFetch 打 warn + 设 error ref,这里静默退出
  // 顶层 stats（各城 ODS 总量、过去 7 天趋势）
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
  // 2026-07-28 Step 2:try/catch 删 — useFetch 已接管错误处理
}

onMounted(loadStats)
</script>

<style scoped>
.admin-page {
  padding: 0 28px 28px;
  min-height: 100vh;
  color: var(--text);
}

/* Header（已迁移至 PageHeader flat 变体） */
.admin-page :deep(.delta) {
  display: inline-block; margin-left: 4px; padding: 1px 5px;
  background: rgba(34,197,94,0.12); color: #16a34a;
  border-radius: 3px; font-size: 9px; font-weight: 600;
}

/* ── 移动端 UI (2026-07-25 P1-fix) ── */
@media (max-width: 768px) {
  .sync-stats { grid-template-columns: 1fr 1fr !important; gap: 8px !important; }
  .city-card-grid { grid-template-columns: 1fr !important; gap: 10px !important; }
  .city-card { padding: 14px 12px !important; }
  .city-card h3 { font-size: 15px !important; }
  .city-card-row { flex-direction: column; align-items: flex-start !important; gap: 4px; }
  .city-card-meta { font-size: 12px; }
  .progress-bar { height: 6px; }
  h1, h2 { font-size: 1.05rem !important; }
  /* 把同步圆点和表格统一切单列 */
  table, thead, tbody, tr, td, th { display: block; width: 100%; }
  thead { display: none; }
  tr { margin-bottom: 12px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; }
  td { padding: 4px 0; border: none; }
}
</style>
