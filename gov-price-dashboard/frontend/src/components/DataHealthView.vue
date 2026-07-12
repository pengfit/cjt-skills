<template>
  <div class="health-page">

    <!-- 四个汇总指标卡（以抓取 skill 为中心） -->
    <div class="health-cards">
      <StatCard icon="📄" label="总数据量" :value="data.total_docs" unit="条" />
      <StatCard icon="🧩" label="抓取任务" :value="skillStats.total" unit="个" />
      <StatCard icon="⏱" label="平均新鲜度" :value="skillStats.avgFreshness" unit="天前" />
      <StatCard
        icon="⚠"
        label="异常告警"
        :value="anomalyStats.total"
        :unit="anomalyStats.total > 0 ? '个 skill 有异常' : '个'"
        :variant="anomalyStats.total > 0 ? 'danger' : 'default'"
      />
    </div>

    <!-- 图表区域 -->
    <div class="chart-panel">
      <SectionHeader title="近 30 日数据量趋势" dot-color="blue">
        <template #right>
          <div class="chart-legend">
            <span class="legend-item"><span class="legend-dot"></span>日增量</span>
            <span class="legend-item" :title="'日增量落在 30 日均值的 [0.3×, 2×] 区间'">
              <span class="legend-dot legend-fresh"></span>正常
              <span class="legend-count">{{ dailyStats.normalCount }}</span>
            </span>
            <span class="legend-item" :title="'日增量 < 30 日均值的 0.3 倍'">
              <span class="legend-dot legend-warn"></span>突减
              <span class="legend-count">{{ dailyStats.dropCount }}</span>
            </span>
            <span class="legend-item" :title="'日增量 > 30 日均值的 2 倍'">
              <span class="legend-dot legend-down"></span>突增
              <span class="legend-count">{{ dailyStats.spikeCount }}</span>
            </span>
          </div>
        </template>
      </SectionHeader>

      <!-- 汇总卡：4 维度速读 -->
      <div class="daily-summary">
        <div class="summary-cell">
          <div class="summary-label">近 30 日新增</div>
          <div class="summary-value">{{ fmt.int(dailyStats.totalCount) }}<span class="summary-unit"> 条</span></div>
        </div>
        <div class="summary-cell">
          <div class="summary-label">活跃天数</div>
          <div class="summary-value">
            {{ dailyStats.activeDays }}<span class="summary-unit"> / 30 天</span>
          </div>
          <div class="summary-sub" v-if="dailyStats.activeDays > 0">覆盖率 {{ dailyStats.coverage }}%</div>
        </div>
        <div class="summary-cell">
          <div class="summary-label">日均（仅活跃日）</div>
          <div class="summary-value">{{ fmt.int(dailyStats.avgPerActiveDay) }}<span class="summary-unit"> 条</span></div>
        </div>
        <div class="summary-cell">
          <div class="summary-label">最大单日</div>
          <div class="summary-value">
            {{ fmt.int(dailyStats.maxCount) }}<span class="summary-unit"> 条</span>
          </div>
          <div class="summary-sub" v-if="dailyStats.maxDate">{{ dailyStats.maxDate }}</div>
        </div>
      </div>

      <div id="dailyTrendChart" class="chart-area"></div>

      <div v-if="dailyStats.activeDays === 0" class="daily-empty-hint">
        近 30 日暂无采集记录，等待首次抓取后即可看到趋势。
      </div>
    </div>

    <!-- 技能数据健康表（以 skill 为中心） -->
    <div class="chart-panel">

      <SectionHeader title="抓取任务数据健康" dot-color="purple">
        <template #right>
          <div class="chart-legend">
            <span class="legend-item"><span class="legend-dot legend-fresh"></span>新鲜</span>
            <span class="legend-item"><span class="legend-dot legend-stale"></span>停滞</span>
            <span class="legend-item"><span class="legend-dot legend-down"></span>停更</span>
            <button class="rule-toggle" @click="showRule = !showRule">
              {{ showRule ? '▴ 收起规则' : '▾ 规则说明' }}
            </button>
          </div>
        </template>
      </SectionHeader>
      <div v-if="showRule" class="rule-panel">
        <div class="rule-grid">
          <div class="rule-section">
            <h5>健康度（按距今 + 同步状态）</h5>
            <div class="rule-row">
              <span class="health-pill pill-fresh">✓ 新鲜</span>
              <span class="rule-desc">距今 <strong>≤ 3 天</strong>，同步状态正常</span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-warn">● 一般</span>
              <span class="rule-desc">距今 <strong>4–7 天</strong>，建议关注</span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-stale">⚠ 停滞</span>
              <span class="rule-desc">距今 <strong>&gt; 7 天</strong>，超一周未抓取</span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-stale">⚠ 中断</span>
              <span class="rule-desc">同步状态 = <code>interrupted</code></span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-down">● 停更</span>
              <span class="rule-desc">同步状态 = <code>down</code></span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-down">✗ 出错</span>
              <span class="rule-desc">同步状态 = <code>error</code></span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-gray">— 无记录</span>
              <span class="rule-desc">缺失 <code>last_updated</code> 字段</span>
            </div>
          </div>
          <div class="rule-section">
            <h5>规格解析率（按 category 平均 rate）</h5>
            <div class="rule-row">
              <span class="rate-pill rate-good">≥ 90%</span>
              <span class="rule-desc"><strong>良好</strong>，解析规则覆盖充分</span>
            </div>
            <div class="rule-row">
              <span class="rate-pill rate-warn">≥ 70%</span>
              <span class="rule-desc"><strong>一般</strong>，部分分类规则待补</span>
            </div>
            <div class="rule-row">
              <span class="rate-pill rate-bad">&lt; 70%</span>
              <span class="rule-desc"><strong>落后</strong>，建议补全规格规则</span>
            </div>
            <div class="rule-meta">
              数据源：<code>/api/stats/spec-quality?city={skill.key}</code>，
              取 <code>coverage</code> 数组所有 category 的 <code>rate</code> 算术平均
            </div>
          </div>
          <div class="rule-section">
            <h5>异常告警（30 日趋势）</h5>
            <div class="rule-row">
              <span class="legend-dot legend-down inline"></span>
              <span class="rule-desc"><strong>突增</strong>：日增量 &gt; 30 日均值的 <strong>2 倍</strong>（红色）</span>
            </div>
            <div class="rule-row">
              <span class="legend-dot legend-warn inline"></span>
              <span class="rule-desc"><strong>突减</strong>：日增量 &lt; 30 日均值的 <strong>0.3 倍</strong>（橙色）</span>
            </div>
            <div class="rule-row">
              <span class="legend-dot legend-fresh inline"></span>
              <span class="rule-desc"><strong>正常</strong>：落在 [0.3×, 2×] 区间内（蓝色）</span>
            </div>
            <div class="rule-meta">
              异常柱用红/橙标色，markPoint 标 ↑/↓ 提示；图中虚线为 30 日均值参考线
            </div>
          </div>
        </div>
      </div>
      <div class="health-table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th class="text-left no-sort">抓取任务</th>
              <th class="no-sort">拼音</th>
              <th class="text-left no-sort">覆盖范围</th>
              <th class="text-right no-sort">文档总数</th>
              <th class="no-sort">最后抓取</th>
              <th class="text-right no-sort">距今</th>
              <th class="no-sort">健康度</th>
              <th class="text-right no-sort">规格解析率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in skillHealthRows" :key="s.key" :class="rowClass(s)">
              <td class="text-left">
                <span class="skill-tag" :class="`tag-${s.barClass}`">{{ s.label }}</span>
              </td>
              <td class="cell-pinyin">{{ s.key }}</td>
              <td class="cell-scope text-left">{{ s.scope }}</td>
              <td class="cell-num text-right">{{ fmt.int(s.total_docs || 0) }}</td>
              <td class="cell-time">{{ s.last_updated || '—' }}</td>
              <td class="cell-num text-right">{{ s.daysAgo === null ? '—' : s.daysAgo + ' 天' }}</td>
              <td>
                <span v-if="s.status === 'error'" class="health-pill pill-down">✗ 出错</span>
                <span v-else-if="s.status === 'interrupted'" class="health-pill pill-stale">⚠ 中断</span>
                <span v-else-if="s.status === 'down'" class="health-pill pill-down">● 停更</span>
                <span v-else-if="s.daysAgo === null" class="health-pill pill-gray">— 无记录</span>
                <span v-else-if="s.daysAgo > 7" class="health-pill pill-stale">⚠ 停滞</span>
                <span v-else-if="s.daysAgo > 3" class="health-pill pill-warn">● 一般</span>
                <span v-else class="health-pill pill-fresh">✓ 新鲜</span>
              </td>
              <td class="cell-num">
                <span v-if="s.spec_rate === null" class="cell-muted">—</span>
                <span v-else :class="rateClass(s.spec_rate)" class="rate-pill">{{ s.spec_rate }}%</span>
                <span v-if="s.spec_total" class="cell-muted cell-muted-small">({{ s.spec_total }} 类)</span>
              </td>
            </tr>
            <tr v-if="!skillHealthRows.length">
              <td colspan="8" class="cell-empty">尚无 skill 数据</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="loading" class="health-loading">
      <SkeletonCard :lines="5" :hide-footer="true" />
    </div>
    <EmptyState v-else-if="!Object.keys(data || {}).length"
      icon="📊" title="暂无数据" message="请稍后再试或检查上游接口" />
    <ErrorState v-if="error" :title="'加载失败'" :message="error" compact :on-retry="loadData" />
  </div>
</template>

<script setup>
import ErrorState from './ErrorState.vue'
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import axios from 'axios'
import { getGovPriceTheme } from '../composables/useEchartsTheme'
import { markRaw } from 'vue'
import { useEcharts } from '../composables/useEcharts'
import { useFormatNumber } from '../composables/useFormatNumber.js'
import SkeletonCard from './SkeletonCard.vue'
import EmptyState from './EmptyState.vue'
import SectionHeader from './SectionHeader.vue'
import StatCard from './StatCard.vue'

const API = import.meta.env.VITE_API_URL || '/api'
const fmt = useFormatNumber()
const loading = ref(false)
const error = ref('')
const data = ref({
  total_docs: 0, province_count: 0,
  daily: [], provinces: []
})

// 以 skill 为中心的数据
const skills = ref([])
const syncDataMap = ref({})
const qualityMap = ref({})  // skill key -> { avg_rate, total_categories, lowest_category }

const SCOPE_MAP = {
  xian: '6 区县',
  sichuan: '21 地市',
  chongqing: '35 区县',
  jinan: '41 分类目录',
  rizhao: '3 类别',
  heze: '期刊',
  henan: '18 地市 / 期刊',
}
const BAR_CLASS_MAP = {
  xian: 'xa', sichuan: 'sc', chongqing: 'cq', jinan: 'jn',
  rizhao: 'rz', heze: 'hz', henan: 'hn',
}

// 近 30 日趋势汇总：总条数 / 活跃天数 / 日均 / 最大 + 异常分类计数
const dailyStats = computed(() => {
  const daily = data.value.daily || []
  const nonZero = daily.filter(d => (d.count || 0) > 0)
  const values = nonZero.map(d => d.count)
  const total = values.reduce((a, b) => a + b, 0)
  const max = values.length ? Math.max(...values) : 0
  const maxItem = max > 0 ? nonZero.find(d => d.count === max) : null
  const avg = values.length ? total / values.length : 0
  const normal = avg > 0 ? nonZero.filter(d => d.count >= avg * 0.3 && d.count <= avg * 2).length : 0
  const drop = avg > 0 ? nonZero.filter(d => d.count < avg * 0.3).length : 0
  const spike = avg > 0 ? nonZero.filter(d => d.count > avg * 2).length : 0
  return {
    totalCount: total,
    activeDays: nonZero.length,
    coverage: Math.round((nonZero.length / 30) * 100),
    avgPerActiveDay: Math.round(avg),
    maxCount: max,
    maxDate: maxItem ? maxItem.date.slice(5) : '',
    normalCount: normal,
    dropCount: drop,
    spikeCount: spike,
  }
})

// 计算每行数据（合并 skill 配置 + 同步进度 + 规格质量）
// 异常严重度（数字越小越严重），用于 #19：异常排序
function healthSeverity(row) {
  if (row.status === 'error') return 0
  if (row.status === 'interrupted' || row.status === 'down') return 1
  if (row.daysAgo === null) return 2
  if (row.daysAgo > 7) return 3
  if (row.daysAgo > 3) return 4
  return 5
}

const skillHealthRows = computed(() => {
  const rows = skills.value.map(s => {
    const sync = syncDataMap.value[s.key] || {}
    const quality = qualityMap.value[s.key] || {}
    const lastUpdated = sync.last_updated || ''
    const daysAgo = lastUpdated ? daysSince(lastUpdated) : null
    return {
      key: s.key,
      label: s.label || s.key,
      barClass: BAR_CLASS_MAP[s.key] || 'xa',
      scope: SCOPE_MAP[s.key] || s.province || '—',
      total_docs: sync.total_docs || 0,
      last_updated: lastUpdated ? lastUpdated.replace('T', ' ').slice(0, 16) : '',
      daysAgo,
      status: sync.status || '',
      spec_rate: quality.avg_rate ?? null,
      spec_total: quality.total_categories ?? 0,
    }
  })
  // 按严重度升序，同严重度内按拼音升序
  return rows.sort((a, b) => {
    const sa = healthSeverity(a)
    const sb = healthSeverity(b)
    if (sa !== sb) return sa - sb
    return a.key.localeCompare(b.key)
  })
})

// 健康度规则说明面板（默认收起）
const showRule = ref(false)

const skillStats = computed(() => {
  const rows = skillHealthRows.value
  const total = rows.length
  const daysList = rows.filter(r => r.daysAgo !== null).map(r => r.daysAgo)
  const avg = daysList.length ? Math.round(daysList.reduce((a, b) => a + b, 0) / daysList.length) : '—'
  const stale = rows.filter(r => r.daysAgo !== null && r.daysAgo > 7).length
  return { total, avgFreshness: avg, staleCount: stale }
})

// 异常告警统计（停滞 + 同步错误 + 突增/突减）
const anomalyStats = computed(() => {
  const rows = skillHealthRows.value
  const daily = data.value.daily || []
  const anomalies = detectAnomalies(daily)
  let stale = 0, errored = 0, anomalyCount = 0
  for (const r of rows) {
    let hasIssue = false
    if (r.daysAgo !== null && r.daysAgo > 7) { stale++; hasIssue = true }
    if (r.status === 'error' || r.status === 'interrupted') { errored++; hasIssue = true }
    if (hasIssue) anomalyCount++
  }
  return { total: anomalyCount, stale, errored, dailyAnomalies: anomalies }
})

function detectAnomalies(buckets) {
  if (!buckets?.length) return { spikes: 0, drops: 0, latest: null }
  const values = buckets.map(b => b.count).filter(v => v > 0)
  if (values.length < 3) return { spikes: 0, drops: 0, latest: null }
  const avg = values.reduce((a, b) => a + b, 0) / values.length
  let spikes = 0, drops = 0, latest = null
  for (let i = 0; i < buckets.length; i++) {
    const v = buckets[i].count
    if (v === 0 || avg === 0) continue
    const ratio = v / avg
    const kind = ratio > 2 ? 'spike' : (ratio < 0.3 ? 'drop' : null)
    if (kind) {
      if (kind === 'spike') spikes++; else drops++
      if (i === buckets.length - 1 || (i === buckets.length - 2 && buckets[buckets.length-1].count === 0)) {
        latest = { date: buckets[i].date, kind, ratio: Math.round(ratio * 10) / 10 }
      }
    }
  }
  return { spikes, drops, latest }
}

function daysSince(ts) {
  if (!ts) return null
  const d = new Date(ts)
  if (isNaN(d.getTime())) return null
  const diff = Date.now() - d.getTime()
  return Math.floor(diff / 86400000)
}

function rowClass(row) {
  if (row.status === 'down' || row.status === 'error') return 'row-down'
  if (row.daysAgo !== null && row.daysAgo > 7) return 'row-stale'
  if (row.daysAgo !== null && row.daysAgo > 3) return 'row-warn'
  return 'row-fresh'
}

function rateClass(rate) {
  if (rate >= 90) return 'rate-good'
  if (rate >= 70) return 'rate-warn'
  return 'rate-bad'
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const [healthRes, regRes] = await Promise.allSettled([
      axios.get(`${API}/stats/data-health`),
      axios.get(`${API}/skill-registry`),
    ])
    if (healthRes.status === 'fulfilled') {
      data.value = healthRes.value.data || {}
    } else {
      console.warn('data-health 加载失败:', healthRes.reason?.message)
    }
    if (regRes.status === 'fulfilled') {
      skills.value = regRes.value.data?.skills || []
    }
    // 并行拉取每个 skill 的同步进度 + 规格质量
    if (skills.value.length) {
      const [syncResults, qualityResults] = await Promise.all([
        Promise.allSettled(
          skills.value.map(s =>
            axios.get(`${API}/stats/${s.key}-sync-progress`, { timeout: 15000 })
              .then(r => ({ key: s.key, data: r.data || {} }))
          )
        ),
        Promise.allSettled(
          skills.value.map(s =>
            axios.get(`${API}/stats/spec-quality`, {
              params: { city: s.key, _sample: false, sample_size: 0 },
              timeout: 20000,
            }).then(r => ({ key: s.key, coverage: r.data?.coverage || [] }))
              .catch(() => ({ key: s.key, coverage: [] }))
          )
        ),
      ])
      const newMap = {}
      for (const r of syncResults) {
        if (r.status === 'fulfilled' && r.value.data) {
          newMap[r.value.key] = r.value.data
        }
      }
      syncDataMap.value = newMap
      const qMap = {}
      for (const r of qualityResults) {
        if (r.status === 'fulfilled') {
          const cov = r.value.coverage || []
          const avg = cov.length ? Math.round(cov.reduce((a, b) => a + (b.rate || 0), 0) / cov.length * 10) / 10 : null
          qMap[r.value.key] = { avg_rate: avg, total_categories: cov.length }
        }
      }
      qualityMap.value = qMap
    }
  } catch (e) {
    console.warn('data-health 加载失败:', e.message)
  }
  error.value = ''
  loading.value = false
  await nextTick()
  renderDailyChart()
}

// 近30日数据量趋势图
async function renderDailyChart() {
  const el = document.getElementById('dailyTrendChart')
  if (!el || !data.value.daily?.length) return
  if (dailyChart.value) { dailyChart.value.dispose(); dailyChart.value = null }
  const echartsMod = await useEcharts()
  const chart = markRaw(echartsMod.init(el, getGovPriceTheme()))
  dailyChart.value = chart

  const buckets = data.value.daily
  const labels = buckets.map(b => b.date.slice(5))
  const values = buckets.map(b => b.count)
  // 0 值改为 null：不画柱子也不占视觉，但 x 轴仍保留位置（让"日期骨架"清晰）
  const plotValues = values.map(v => (v > 0 ? v : null))
  // 计算异常点（>平均 2 倍 = spike 突增，<0.3 倍 = drop 突减）
  const nonZero = values.filter(v => v > 0)
  const avg = nonZero.length ? nonZero.reduce((a, b) => a + b, 0) / nonZero.length : 0
  const markPoints = []
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    if (v === 0 || avg === 0) continue
    const ratio = v / avg
    if (ratio > 2) markPoints.push({ idx: i, kind: 'spike', v, ratio })
    else if (ratio < 0.3) markPoints.push({ idx: i, kind: 'drop', v, ratio })
  }

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.98)', borderColor: '#cbd5e1', borderWidth: 1,
      textStyle: { color: '#0f172a', fontSize: 12 },
      formatter: p => {
        const i = p[0].dataIndex
        const v = values[i]
        if (v === 0) return `<b style="color:#94a3b8">${p[0].name}</b><br/><span style="color:#94a3b8">无采集</span>`
        const avgLine = avg > 0 ? `<br/>30日均: ${fmt.int(Math.round(avg))}` : ''
        const ratio = avg > 0 ? (v / avg).toFixed(2) : '-'
        const flag = avg > 0 && (v / avg > 2 || v / avg < 0.3)
          ? `<br/><b style="color:${v/avg > 2 ? '#dc2626' : '#ea580c'}">${v/avg > 2 ? '↑ 突增' : '↓ 突减'} (×${ratio})</b>` : ''
        return `<b style="color:#3b82f6">${p[0].name}</b><br/>数量: <b style="color:#10b981">${fmt.int(v)}</b>${avgLine}${flag}`
      }
    },
    grid: { left: '3%', right: '3%', bottom: '10%', top: '18%', containLabel: true },
    xAxis: {
      type: 'category', data: labels,
      axisLabel: {
        color: '#475569', fontSize: 10, rotate: 45, interval: 0,
        formatter: (v, idx) => {
          // 活跃日的标签加粗+主色，无数据日弱化
          return values[idx] > 0 ? `{active|${v}}` : `{idle|${v}}`
        },
        rich: {
          active: { color: '#0f172a', fontWeight: 600 },
          idle: { color: '#cbd5e1' }
        }
      },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false },
      splitLine: { show: false }
    },
    yAxis: {
      name: '文档数', nameTextStyle: { color: '#64748b', fontSize: 10, padding: [0, 0, 0, 30] },
      type: 'value',
      axisLabel: { color: '#64748b', fontSize: 10, formatter: v => v >= 1000 ? (v/1000).toFixed(0)+'k' : v },
      splitLine: { lineStyle: { color: '#e2e8f0', type: 'dashed' } }
    },
    series: [{
      type: 'bar', data: plotValues,
      itemStyle: {
        color: p => {
          if (p.value == null) return 'transparent'
          if (avg > 0) {
            const ratio = p.value / avg
            if (ratio > 2) return '#dc2626'  // 突增 - 红
            if (ratio < 0.3) return '#ea580c'  // 突减 - 橙
          }
          return new echartsMod.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#2563eb' },
            { offset: 1, color: '#6366f1' }
          ])
        },
        borderRadius: [4, 4, 0, 0]
      },
      label: {
        show: true,
        position: 'top',
        formatter: p => (p.value > 0 ? fmt.int(p.value) : ''),
        color: '#475569',
        fontSize: 10,
        fontWeight: 600
      },
      markLine: avg > 0 ? {
        silent: true,
        symbol: 'none',
        lineStyle: { color: '#94a3b8', type: 'dashed', width: 1 },
        label: { show: true, position: 'insideEndTop', formatter: `30日均 ${fmt.int(Math.round(avg))}`, color: '#64748b', fontSize: 10, backgroundColor: 'rgba(255,255,255,0.9)', padding: [2, 4] },
        data: [{ yAxis: avg }]
      } : undefined,
      markPoint: markPoints.length ? {
        symbol: 'pin',
        symbolSize: 28,
        symbolOffset: [0, -22],
        data: markPoints.map(m => ({
          name: m.kind === 'spike' ? '突增' : '突减',
          value: m.kind === 'spike' ? '↑' : '↓',
          xAxis: m.idx,
          yAxis: m.v,
          itemStyle: { color: m.kind === 'spike' ? '#dc2626' : '#ea580c' }
        })),
        label: { color: '#fff', fontSize: 11, fontWeight: 700 }
      } : undefined,
      barMaxWidth: 28,
      emphasis: {
        itemStyle: { color: new echartsMod.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#2563eb' },
          { offset: 1, color: '#818cf8' }
        ]) }
      }
    }],
  })
  if (dailyResizeHandler) window.removeEventListener('resize', dailyResizeHandler)
  dailyResizeHandler = () => chart.resize()
  window.addEventListener('resize', dailyResizeHandler)
}

const dailyChart = ref(null)
let dailyResizeHandler = null

onMounted(async () => {
  await loadData()
})

onUnmounted(() => {
  if (dailyResizeHandler) window.removeEventListener('resize', dailyResizeHandler)
})
</script>

<style scoped>
/* === 亮色版 === */
.health-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 20px;
  padding-top: 16px;
  min-height: 100vh;
  background: linear-gradient(180deg, var(--bg) 0%, var(--surface-2) 100%);
  position: static;
  z-index: 10;
  box-sizing: border-box;
  color: var(--surface);
}

/* ===== 顶部汇总指标卡（已迁移至 StatCard 组件） ===== */
.health-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}

/* ===== 表格内文字辅助颜色 ===== */
.text-up   { color: var(--status-ok); }
.text-down { color: var(--danger); }

/* ===== 图表面板 ===== */
.chart-panel {
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 1px 2px rgba(var(--text-rgb), 0.04), 0 2px 6px rgba(var(--text-rgb), 0.03);
  flex-shrink: 0;
}
/* panel-header / panel-title / panel-dot 已迁移至 SectionHeader.vue */
.chart-legend { display: flex; gap: 16px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
.legend-dot { width: 10px; height: 10px; border-radius: 2px; background: linear-gradient(135deg, var(--primary), var(--indigo)); }
.chart-area { width: 100%; height: 320px; }

/* ===== 近 30 日汇总卡 ===== */
.daily-summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin: 4px 0 14px;
}
.summary-cell {
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 14px;
  position: relative;
  overflow: hidden;
}
.summary-cell::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: var(--primary);
  border-radius: 10px 0 0 10px;
}
.summary-label {
  font-size: 11px;
  color: var(--text-3);
  margin-bottom: 4px;
  letter-spacing: 0.2px;
}
.summary-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.summary-unit {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-3);
  margin-left: 2px;
}
.summary-sub {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 2px;
}

/* 图例计数 */
.legend-count {
  display: inline-block;
  min-width: 18px;
  padding: 0 5px;
  margin-left: 4px;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-2);
  background: rgba(15, 23, 42, 0.06);
  border-radius: 8px;
  text-align: center;
  line-height: 16px;
}

/* 空状态提示 */
.daily-empty-hint {
  margin-top: 12px;
  padding: 10px 14px;
  background: rgba(96, 165, 250, 0.06);
  border: 1px dashed rgba(37, 99, 235, 0.2);
  border-radius: 8px;
  color: var(--text-2);
  font-size: 12px;
  text-align: center;
}

/* 7 城同步卡片已从本视图移除（避免与同步页抓取任务重复），卡片逻辑迁到 components/SyncCard.vue 仅供其他视图使用 */

/* ===== 技能数据健康表（以 skill 为中心）===== */
.legend-fresh { background: #16a34a; }
.legend-warn { background: #ea580c; }
.legend-stale { background: #ea580c; }
.legend-down  { background: #dc2626; }

.health-table-scroll {
  /* 不要让表格容器自身产生滚动条——让表格自然撑开，页面整体滚 */
  overflow-x: auto;
}
.data-table .cell-num { font-variant-numeric: tabular-nums; }
.data-table .cell-time { color: var(--text-2); font-family: ui-monospace, 'SF Mono', Consolas, monospace; font-size: 11.5px; }
.data-table .cell-scope { color: var(--text-2); }
.data-table .cell-empty { text-align: center; color: var(--text-3); padding: 24px; }

.row-fresh td:first-child { border-left: 3px solid #16a34a; }
.row-warn  td:first-child { border-left: 3px solid #ea580c; }
.row-stale td:first-child { border-left: 3px solid #dc2626; }
.row-down  td:first-child { border-left: 3px solid #dc2626; background: rgba(220, 38, 38, 0.04); }

.skill-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  margin-right: 6px;
}
.tag-xa { background: #fff7ed; color: #c2410c; }
.tag-sc { background: #ecfdf5; color: #047857; }
.tag-cq { background: #fdf2f8; color: #be185d; }
.tag-jn { background: #eef2ff; color: #4338ca; }
.tag-rz { background: #f0fdfa; color: #0f766e; }
.tag-hz { background: #faf5ff; color: #7e22ce; }
.tag-hn { background: #fef2f2; color: #b91c1c; }

.skill-key {
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 11px;
  color: var(--text-3);
}

.cell-pinyin {
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 11.5px;
  color: var(--text-2);
  white-space: nowrap;
}

.health-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}
.pill-fresh { background: #d1fae5; color: #047857; }
.pill-warn  { background: #fed7aa; color: #c2410c; }
.pill-stale { background: #fee2e2; color: #b91c1c; }
.pill-down  { background: #fee2e2; color: #b91c1c; }
.pill-gray  { background: var(--text); color: var(--text-2); }

.rate-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.rate-good { background: #d1fae5; color: #047857; }
.rate-warn { background: #fed7aa; color: #c2410c; }
.rate-bad  { background: #fee2e2; color: #b91c1c; }

.cell-muted { color: var(--text-3); font-size: 11px; }
.cell-muted-small { font-size: 10px; margin-left: 2px; }

/* ===== 规则说明面板（折叠）===== */
.rule-toggle {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--primary);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.rule-toggle:hover {
  background: var(--primary-light);
  border-color: var(--primary);
}

.rule-panel {
  background: rgba(241, 245, 249, 0.6);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 12px;
  font-size: 12px;
}
.rule-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
.rule-section h5 {
  margin: 0 0 10px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 0.2px;
}
.rule-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  color: var(--text-2);
}
.rule-row strong { color: var(--text); font-weight: 700; }
.rule-row code {
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 11px;
  background: rgba(37, 99, 235, 0.08);
  color: var(--primary);
  padding: 1px 5px;
  border-radius: 3px;
}
.rule-desc { font-size: 12px; }
.rule-meta {
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.6;
  border-top: 1px dashed var(--border);
  padding-top: 6px;
}
.legend-dot.inline { display: inline-block; margin: 0; }

@media (max-width: 1100px) {
  .rule-grid { grid-template-columns: 1fr; }
}

</style>
