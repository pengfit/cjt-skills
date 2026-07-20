<!--
  ShowcaseMap.vue (2026-07-19 A 风格改造)

  简约版 — 比 B 风格再轻一档:
  - 高度 360px(从 460px 降)
  - tooltip 只显示省名 + 条数,不带城市列表
  - 配色保持 5 档色阶
-->
<template>
  <section class="map-coverage" id="coverage">
    <header class="section-head">
      <h2 class="section-title">Agent 触达范围</h2>
      <p class="section-sub">
        {{ totalCities }} 城 · {{ provinces.length }} 省 · 凌晨 01:00–02:25 自动巡检,颜色深浅 = 昨日入库量
      </p>
    </header>
    <div ref="chartEl" class="map-chart"></div>
    <div class="legend">
      <span class="legend-label">数据量</span>
      <div class="legend-bar">
        <span class="legend-stop" style="background: #f1f5f9"></span>
        <span class="legend-stop" style="background: #dbeafe"></span>
        <span class="legend-stop" style="background: #93c5fd"></span>
        <span class="legend-stop" style="background: #3b82f6"></span>
        <span class="legend-stop" style="background: #1d4ed8"></span>
      </div>
      <div class="legend-ticks">
        <span>无</span>
        <span>1+</span>
        <span>1k+</span>
        <span>10k+</span>
        <span>100k+</span>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useEcharts } from '../../composables/useEcharts'
import { registerGovPriceTheme } from '../../composables/useEchartsTheme'

const props = defineProps({
  grouped: { type: Array, default: () => [] },
})

const chartEl = ref(null)
let chart = null

const totalCities = computed(() =>
  props.grouped.reduce((s, p) => s + (p.cities?.length || 0), 0)
)
const provinces = computed(() => props.grouped)

const PROVINCE_FULL_NAME = {
  '内蒙古': '内蒙古自治区',
  '吉林': '吉林省',
  '四川': '四川省',
  '宁夏': '宁夏回族自治区',
  '山东': '山东省',
  '山西': '山西省',
  '新疆': '新疆维吾尔自治区',
  '江西': '江西省',
  '河南': '河南省',
  '海南': '海南省',
  '湖南': '湖南省',
  '贵州': '贵州省',
  '重庆': '重庆市',
  '陕西': '陕西省',
  '青海': '青海省',
}

async function loadAndRender() {
  if (!chartEl.value) return
  try {
    await registerGovPriceTheme()
    const echarts = await useEcharts()

    const r = await fetch('/geo/100000_full.json')
    const geo = await r.json()
    // 2026-07-19:道友要求保留海南主岛,但删除南海诸岛小岛
    // 海南省(adcode=460000)的 geometry 是 MultiPolygon,共 133 个 Polygon:
    //   - Polygon[0] = 海南主岛(106 点,lat 18-20°N)
    //   - Polygon[1..132] = 南海诸岛(永兴/中业/曾母暗沙等岛礁,lat 3-17°N)
    // 这里只保留 Polygon[0],南海小岛全部丢弃
    const filtered = {
      ...geo,
      features: geo.features.map(f => {
        if (f.properties.adcode !== 460000) return f
        if (f.geometry.type !== 'MultiPolygon') return f
        return {
          ...f,
          geometry: {
            type: 'Polygon',
            coordinates: f.geometry.coordinates[0],
          },
        }
      }),
    }
    echarts.registerMap('china', filtered)

    const provinceTotals = new Map()
    for (const p of props.grouped) {
      const total = (p.cities || []).reduce((s, c) => s + (c.count || 0), 0)
      provinceTotals.set(p.name, total)
    }

    const data = geo.features.map(f => {
      const fullName = f.properties.name
      let shortName = fullName
      let value = 0
      for (const [short, full] of Object.entries(PROVINCE_FULL_NAME)) {
        if (full === fullName) {
          shortName = short
          value = provinceTotals.get(short) || 0
          break
        }
      }
      return { name: fullName, value, _short: shortName }
    })

    chart = echarts.init(chartEl.value, 'govPrice', { renderer: 'canvas' })
    chart.setOption({
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(255, 255, 255, 0.97)',
        borderColor: '#e2e8f0',
        borderWidth: 1,
        padding: [8, 12],
        textStyle: { color: '#0f172a', fontSize: 13, fontFamily: 'var(--font-sans)' },
        extraCssText: 'box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08); border-radius: 8px;',
        formatter: (params) => {
          const d = params.data
          const display = d?._short && d._short !== d.name ? d._short : d?.name || params.name
          if (!d || !d.value) {
            return `<div style="font-weight:600;font-size:13px">${display}</div>`
              + `<div style="color:#94a3b8;font-size:11px;margin-top:2px">暂无数据</div>`
          }
          return `<div style="font-weight:600;font-size:13px">${display}</div>`
            + `<div style="color:#1e40af;font-weight:600;font-family:var(--font-mono-num);margin-top:2px">${d.value.toLocaleString()} 条</div>`
        },
      },
      series: [
        {
          type: 'map',
          map: 'china',
          roam: false,
          // 2026-07-19:之前 zoom=1.5 + layoutSize=100% 会让地图溢出容器、北部被裁
          // 改为不加 zoom,让 layoutSize='100%' 自然填满 600px 容器,无溢出
          aspectScale: 0.85,
          layoutCenter: ['50%', '50%'],
          layoutSize: '100%',
          label: { show: false },
          itemStyle: {
            borderColor: '#cbd5e1',
            borderWidth: 0.6,
            areaColor: '#f1f5f9',
          },
          emphasis: {
            label: { show: false },
            itemStyle: {
              areaColor: '#2563eb',
              borderColor: '#1e40af',
              borderWidth: 1,
            },
          },
          select: {
            label: { show: false },
            itemStyle: { areaColor: '#1e40af' },
          },
          data: data,
        },
      ],
      visualMap: {
        type: 'piecewise',
        show: false,
        pieces: [
          { min: 100000, color: '#1d4ed8' },
          { min: 10000, max: 99999, color: '#3b82f6' },
          { min: 1000, max: 9999, color: '#93c5fd' },
          { min: 1, max: 999, color: '#dbeafe' },
          { value: 0, color: '#f1f5f9' },
        ],
      },
    })
  } catch (e) {
    console.error('[showcase-map] 加载失败:', e)
  }
}

function onResize() {
  if (chart) chart.resize()
}

onMounted(() => {
  loadAndRender()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (chart) {
    chart.dispose()
    chart = null
  }
})
</script>

<style scoped>
.map-coverage {
  padding: 64px 0 48px;
}

.section-head {
  margin-bottom: 24px;
}

.section-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.02em;
  margin: 0 0 8px;
}

.section-sub {
  font-size: 14px;
  color: var(--text-2);
  margin: 0;
}

.map-chart {
  width: 100%;
  height: 700px;
  background: transparent;
}

.legend {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 16px;
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  width: fit-content;
  margin-left: auto;
  margin-right: auto;
}

.legend-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
}

.legend-bar {
  display: flex;
  height: 10px;
  border-radius: 2px;
  overflow: hidden;
  border: 1px solid var(--border);
}

.legend-stop {
  width: 24px;
  height: 100%;
}

.legend-ticks {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono-num);
}

.legend-ticks span {
  width: 24px;
  text-align: center;
}

@media (max-width: 640px) {
  .map-chart { height: 520px; }
  .legend { flex-wrap: wrap; gap: 8px; }
  .legend-ticks span { width: auto; }
}
</style>
