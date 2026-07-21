<!--
  ShowcaseCase.vue (2026-07-20 新增 - OPC 整合)

  把原 3 个 section 合并为一个综合"案例":
  - OPC 运行时架构(讲技术怎么搭)
  - Agent 触达范围(讲数据从哪来)
  - OPC 跑通的工作流(讲 5 步时间线)

  这 3 个讲的是同一个事: 建筑材料造价数据从政府源站 → 入仓 → 服务 → 用户的端到端整合案例。
  合并后: 顶部 5 列工作成果 + 中部 5 步时间线 + 20 数据源覆盖,讲清"OPC 怎么用"。

  分工:
  - Workspace: 怎么工作(AI 协作范式)
  - Case: 跑通了什么(具体案例)
-->
<template>
  <section class="case" id="case">
    <header class="section-head">
      <h2 class="section-title">
        案例：材价通
      </h2>
      <p class="section-sub">
        20 数据源串行 · 凌晨 cron 自跑 0 干预
      </p>
    </header>

    <!-- 项目业务描述 (道友反馈 2026-07-20 15:39) -->
    <div class="case-business">
      <p class="case-business-lead">
        <strong>材价通</strong>是为工程造价行业打造的材料价格数据中台。它对接各地住建局/造价站官方发布的材料价格信息，凌晨自动归集、清洗、跨城归一，覆盖 20 数据源 9,931 个跨城统一品类。
      </p>
      <div class="case-business-grid">
        <div class="case-business-cell">
          <span class="case-business-icon">👥</span>
          <div class="case-business-body">
            <div class="case-business-label">谁在用</div>
            <div class="case-business-text">工程造价公司 · 造价咨询 · 施工单位 · 政府审计 · 建材厂商</div>
          </div>
        </div>
        <div class="case-business-cell">
          <span class="case-business-icon">⚡</span>
          <div class="case-business-body">
            <div class="case-business-label">解决什么</div>
            <div class="case-business-text">人工汇总 20 数据源 · 跨口径不一 · 期刊滞后查询 · 历史趋势缺失</div>
          </div>
        </div>
        <div class="case-business-cell">
          <span class="case-business-icon">📈</span>
          <div class="case-business-body">
            <div class="case-business-label">带来什么</div>
            <div class="case-business-text">秒级跨城检索 · 时序趋势 · 规格自动归一 · 公开数据无需登录 · 鉴权 API 可对接</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 顶部:5 列工作成果数字看板 -->
    <div class="case-results">
      <article class="case-result" v-for="(r, i) in results" :key="i">
        <div class="case-result-num">{{ r.num }}</div>
        <div class="case-result-unit">{{ r.unit }}</div>
        <div class="case-result-label">{{ r.label }}</div>
      </article>
    </div>

    <!-- 中部:20 数据源覆盖 -->
    <div class="case-map">
      <div ref="mapEl" class="case-map-chart"></div>
      <div class="case-map-legend">
        <span class="case-map-legend-label">数据量</span>
        <div class="case-map-legend-bar">
          <span style="background: #f1f5f9"></span>
          <span style="background: #dbeafe"></span>
          <span style="background: #93c5fd"></span>
          <span style="background: #3b82f6"></span>
          <span style="background: #1d4ed8"></span>
        </div>
        <div class="case-map-legend-ticks">
          <span>无</span>
          <span>1+</span>
          <span>1k+</span>
          <span>10k+</span>
          <span>100k+</span>
        </div>
      </div>
    </div>

    <!-- 5 步端到端时间线(纵向 · 三列 grid: 时间 | 圆点+虚线 | 卡片) -->
    <div class="case-timeline">
      <div class="case-timeline-head">
        <h3>数据处理步骤</h3>
        <span class="case-timeline-meta">凌晨 cron → 中台展示 · 全程 0 干预</span>
      </div>
      <div class="case-timeline-flow">
        <article v-for="(s, i) in steps" :key="i" class="case-step">
          <div class="case-step-time">{{ s.time }}</div>
          <div class="case-step-rail">
            <span class="case-step-dot"></span>
            <span class="case-step-line" v-if="i < steps.length - 1"></span>
          </div>
          <div class="case-step-body">
            <div class="case-step-head">
              <span class="case-step-num">0{{ i + 1 }}</span>
              <h4 class="case-step-title">{{ s.title }}</h4>
            </div>
            <p class="case-step-desc">{{ s.desc }}</p>
            <div class="case-step-snippet">
              <span class="case-step-label">{{ s.label }}</span>
              <code>{{ s.snippet }}</code>
            </div>
            <div class="case-step-output">
              <span class="case-step-arrow">→</span>
              <span>{{ s.output }}</span>
            </div>
          </div>
        </article>
      </div>
    </div>

    <!-- 底部:案例总结(技术栈 2026-07-21 移除) -->
    <div class="case-footer">
      <div class="case-summary">
        <strong>这个案例展示 饲养员场地怎么用 AI 跑通一个完整业务：</strong>
        20 数据源串行 → 凌晨 cron 自动抓取 → ETL 三层入仓 →
        AI 协作归一 → Vue Dashboard 服务客户 → 飞书告警通知。
        1 人公司 + AI 全程无需干预，覆盖数据业务全生命周期。
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useEcharts } from '../../composables/useEcharts'
import { registerGovPriceTheme } from '../../composables/useEchartsTheme'

const mapEl = ref(null)
let chart = null

const results = [
  { num: '20', unit: '源', label: '数据采集' },
  { num: '9,931', unit: '品种', label: '跨城归一' },
  { num: '788,525', unit: '条', label: '服务交付' },
  { num: '7×24', unit: '自跑', label: '部署运维' },
]

const steps = [
  {
    time: '第一步',
    title: 'Agent 触发 cron',
    desc: 'OpenClaw + cron 自动调度 · 20 数据源凌晨抓取',
    label: 'CRON',
    snippet: 'Agent 调度 · 20 数据源串行 · 失败重试 3 次',
    output: '飞书实时告警，异常不阻塞下一城',
  },
  {
    time: '第二步',
    title: 'HTML + PDF 解析入仓',
    desc: 'Excel + PDF（OCR） + Html + API · 解析入 ODS 原始层',
    label: '入仓',
    snippet: 'ODS 原始层 · +234 条带审计字段',
    output: '可追溯、可回放、可重跑',
  },
  {
    time: '第三步',
    title: 'ETL 三层转换',
    desc: '清洗 + 跨城映射 · 9,931 品种跨城口径统一',
    label: '归一',
    snippet: 'C30 混凝土 → 商品混凝土 C30',
    output: '1.2 万品种跨城口径统一',
  },
  {
    time: '第四步',
    title: '材价通汇总和展示',
    desc: 'ES 聚合查询 + Vue Dashboard 渲染 · 公开数据无需登录',
    label: 'DASHBOARD',
    snippet: '聚合接口 · 9 个驾驶舱 Tab · 20 城 / 78.9 万条 / 9,931 品种',
    output: '公开 / 鉴权分流 · 1 人 = 1 家公司',
  },
]

// 中国地图(20 数据源覆盖)
const PROVINCE_FULL_NAME = {
  '内蒙古': '内蒙古自治区', '吉林': '吉林省', '四川': '四川省',
  '宁夏': '宁夏回族自治区', '山东': '山东省', '山西': '山西省',
  '新疆': '新疆维吾尔自治区', '江西': '江西省', '河南': '河南省',
  '海南': '海南省', '湖南': '湖南省', '贵州': '贵州省',
  '重庆': '重庆市', '陕西': '陕西省', '青海': '青海省',
}

// 20 数据源数据
const provincesGrouped = [
  { name: '内蒙古', cities: [{ key: 'huhehaote', label: '呼和浩特', count: 1803 }] },
  { name: '吉林', cities: [{ key: 'jilin', label: '吉林', count: 5124 }] },
  { name: '四川', cities: [{ key: 'sichuan', label: '四川', count: 421345 }] },
  { name: '宁夏', cities: [{ key: 'ningxia', label: '宁夏', count: 7747 }] },
  { name: '山东', cities: [
    { key: 'weihai', label: '威海', count: 818 },
    { key: 'rizhao', label: '日照', count: 4973 },
    { key: 'jinan', label: '济南', count: 24487 },
    { key: 'heze', label: '菏泽', count: 868 },
    { key: 'qingdao', label: '青岛', count: 1307 },
  ] },
  { name: '山西', cities: [{ key: 'shanxi', label: '山西', count: 11436 }] },
  { name: '新疆', cities: [{ key: 'xinjiang', label: '新疆', count: 100990 }] },
  { name: '江西', cities: [{ key: 'jiangxi', label: '江西', count: 45579 }] },
  { name: '河南', cities: [{ key: 'henan', label: '河南', count: 8234 }] },
  { name: '海南', cities: [{ key: 'hainan', label: '海南', count: 12278 }] },
  { name: '湖南', cities: [{ key: 'hunan', label: '湖南', count: 2282 }] },
  { name: '贵州', cities: [{ key: 'guizhou', label: '贵州', count: 17072 }] },
  { name: '重庆', cities: [{ key: 'chongqing', label: '重庆', count: 8578 }] },
  { name: '陕西', cities: [
    { key: 'xian', label: '西安', count: 69654 },
    { key: 'shaanxi', label: '陕西', count: 33475 },
  ] },
  { name: '青海', cities: [{ key: 'qinghai', label: '青海', count: 10475 }] },
]

async function loadAndRender() {
  if (!mapEl.value) return
  try {
    await registerGovPriceTheme()
    const echarts = await useEcharts()
    const r = await fetch('/geo/100000_full.json')
    const geo = await r.json()
    const filtered = {
      ...geo,
      features: geo.features.map(f => {
        if (f.properties.adcode !== 460000) return f
        if (f.geometry.type !== 'MultiPolygon') return f
        return { ...f, geometry: { type: 'Polygon', coordinates: f.geometry.coordinates[0] } }
      }),
    }
    echarts.registerMap('china', filtered)

    const provinceTotals = new Map()
    for (const p of provincesGrouped) {
      const total = (p.cities || []).reduce((s, c) => s + (c.count || 0), 0)
      provinceTotals.set(p.name, total)
    }
    const data = geo.features.map(f => {
      const fullName = f.properties.name
      let shortName = fullName
      let value = 0
      for (const [short, full] of Object.entries(PROVINCE_FULL_NAME)) {
        if (full === fullName) { shortName = short; value = provinceTotals.get(short) || 0; break }
      }
      return { name: fullName, value, _short: shortName }
    })

    chart = echarts.init(mapEl.value, 'govPrice', { renderer: 'canvas' })
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
            return `<div style="font-weight:600;font-size:13px">${display}</div>` +
              `<div style="color:#94a3b8;font-size:11px;margin-top:2px">暂无数据</div>`
          }
          return `<div style="font-weight:600;font-size:13px">${display}</div>` +
            `<div style="color:#1e40af;font-weight:600;font-family:var(--font-mono-num);margin-top:2px">${d.value.toLocaleString()} 条</div>`
        },
      },
      series: [{
        type: 'map', map: 'china', roam: false,
        aspectScale: 0.85,
        layoutCenter: ['50%', '50%'],
        layoutSize: '100%',
        label: { show: false },
        itemStyle: { borderColor: '#cbd5e1', borderWidth: 0.6, areaColor: '#f1f5f9' },
        emphasis: {
          label: { show: false },
          itemStyle: { areaColor: '#2563eb', borderColor: '#1e40af', borderWidth: 1 },
        },
        data: data,
      }],
      visualMap: {
        type: 'piecewise', show: false,
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
    console.error('[case-map] 加载失败:', e)
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
  if (chart) { chart.dispose(); chart = null }
})
</script>

<style scoped>
.case {
  padding: 96px 0 56px;  /* 2026-07-20 #3 间距统一 */
  border-top: 1px solid var(--border-light);
}

.section-head {
  margin-bottom: 32px;
}

.section-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.02em;
  margin: 0 0 8px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.section-title .opc-icon-inline {
  color: var(--primary);
  flex-shrink: 0;
}

.section-sub {
  font-size: 14px;
  color: var(--text-2);
  margin: 0;
}

/* ── 业务描述块 (道友反馈 2026-07-20) ── */
.case-business {
  margin-bottom: 32px;
  padding: 20px 24px;
  background: var(--surface-2);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
}

.case-business-lead {
  font-size: 14px;
  line-height: 1.75;
  color: var(--text-2);
  margin: 0 0 16px;
}

.case-business-lead strong {
  color: var(--primary);
  font-weight: 700;
}

.case-business-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.case-business-cell {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  background: var(--surface);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
}

.case-business-icon {
  font-size: 18px;
  line-height: 1.2;
  flex-shrink: 0;
}

.case-business-body {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.case-business-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  letter-spacing: 0.04em;
}

.case-business-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
}

/* ── 顶部 5 列工作成果 ── */
.case-results {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
  margin-bottom: 48px;
}

.case-result {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 16px;
  text-align: center;
  transition: all 0.2s ease;
}

.case-result:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm, 0 2px 8px rgba(0, 0, 0, 0.03));
  transform: translateY(-2px);
}

.case-result-num {
  font-size: 32px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono-num);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1;
}

.case-result-unit {
  font-size: 13px;
  color: var(--text-2);
  font-weight: 500;
  margin-top: 4px;
}

.case-result-label {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 8px;
  letter-spacing: 0.02em;
}

/* ── 中部 20 数据源地图(无卡背景,融入页面) ── */
.case-map {
  margin-bottom: 48px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0;
}

.case-map-chart {
  width: 100%;
  height: 600px;
  background: transparent;
}

.case-map-legend {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 12px;
  padding: 8px 12px;
  background: var(--surface-2);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  width: fit-content;
  margin-left: auto;
  margin-right: auto;
}

.case-map-legend-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
}

.case-map-legend-bar {
  display: flex;
  height: 10px;
  border-radius: 2px;
  overflow: hidden;
  border: 1px solid var(--border);
}

.case-map-legend-bar span {
  width: 24px;
  height: 100%;
}

.case-map-legend-ticks {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono-num);
}

.case-map-legend-ticks span {
  width: 24px;
  text-align: center;
}

/* ── 5 步时间线 (道友反馈 2026-07-20 v2: 三列 grid, 圆点独立 rail) ── */
.case-timeline {
  margin-bottom: 48px;
}

.case-timeline-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 24px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-light);
}

.case-timeline-head h3 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  letter-spacing: -0.01em;
}

.case-timeline-meta {
  font-size: 12px;
  color: var(--text-3);
  font-family: var(--font-mono-num);
}

.case-timeline-flow {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 三列 grid: 时间列 | 圆点+虚线 rail | 卡片 */
.case-step {
  display: grid;
  grid-template-columns: 64px 20px 1fr;
  align-items: stretch;
  gap: 0;
  position: relative;
}

.case-step-time {
  font-size: 13px;
  font-weight: 600;
  color: var(--primary);
  font-family: var(--font-mono-num);
  padding-top: 12px;
  padding-right: 20px;  /* 2026-07-20 16:04 圆点-时间列间隙 = 圆点-卡片间隙 (body padding-left) */
  line-height: 1.3;
  text-align: right;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

/* 中间 rail 列: 圆点 + 虚线 */
.case-step-rail {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 18px;
}

.case-step-dot {
  position: relative;  /* 2026-07-20 #13 脉冲环 anchor */
  width: 10px;
  height: 10px;
  background: var(--surface);
  border: 2px solid var(--primary);
  border-radius: 50%;
  z-index: 1;
  flex-shrink: 0;
}

/* 2026-07-20 #13: 脉冲呼吸圈 (外环 scale 1→2.2, 透明度 0.7→0, 1.8s 循环) */
.case-step-dot::after {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 50%;
  border: 2px solid var(--primary);
  opacity: 0.7;
  animation: case-pulse-ring 1.8s cubic-bezier(0.4, 0, 0.6, 1) infinite;
  pointer-events: none;
}

@keyframes case-pulse-ring {
  0% { transform: scale(1); opacity: 0.7; }
  80% { opacity: 0; }
  100% { transform: scale(2.2); opacity: 0; }
}

/* hover 暂停, 视觉反馈 "读这条" */
.case-step:hover .case-step-dot::after {
  animation-play-state: paused;
}

.case-step-line {
  flex: 1;
  width: 1px;
  margin-top: 4px;
  background-image: linear-gradient(
    to bottom,
    var(--border) 0,
    var(--border) 4px,
    transparent 4px,
    transparent 14px
  );
  background-size: 1px 14px;
}

.case-step-body {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 14px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: all 0.2s ease;
}

.case-step-body:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm, 0 2px 8px rgba(0, 0, 0, 0.03));
}

/* num 跟 title 横排, 不再垂直堆叠 */
.case-step-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.case-step-num {
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono-num);
  letter-spacing: 0.04em;
  background: var(--primary-dim, rgba(37, 99, 235, 0.08));
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}

.case-step-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
  letter-spacing: -0.01em;
  line-height: 1.3;
}

.case-step-desc {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-2);
  margin: 0;
}

.case-step-snippet {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface-2);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  padding: 6px 10px;
  overflow-x: auto;
  font-family: var(--font-mono-num);
}

.case-step-label {
  font-size: 9px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-dim, rgba(37, 99, 235, 0.08));
  padding: 1px 4px;
  border-radius: 2px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  flex-shrink: 0;
}

.case-step-snippet code {
  font-size: 11px;
  color: var(--text);
  white-space: nowrap;
  flex: 1;
}

.case-step-output {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 11px;
  color: var(--text-3);
  margin: 0;
}

.case-step-arrow {
  color: var(--primary);
  font-weight: 700;
  font-family: var(--font-mono-num);
}

/* ── 底部技术栈 + 总结 ── */
.case-footer {
  padding: 20px 24px;
  background: linear-gradient(135deg, var(--primary-dim, rgba(37, 99, 235, 0.06)) 0%, var(--surface) 100%);
  border: 1px solid var(--primary);
  border-radius: var(--radius-lg);
}

.case-summary {
  font-size: 13px;
  line-height: 1.75;
  color: var(--text-2);
}

.case-summary strong {
  color: var(--primary);
  font-weight: 700;
  margin-right: 4px;
}

@media (max-width: 1024px) {
  .case-results { grid-template-columns: repeat(3, 1fr); }
  .case-business-grid { grid-template-columns: 1fr; }
  .case-map-chart { height: 520px; }
}

@media (max-width: 640px) {
  .case-results { grid-template-columns: 1fr; }
  .case-map-chart { height: 400px; }
  .case-step { grid-template-columns: 48px 16px 1fr; }
  .case-step-time { font-size: 11px; padding-right: 8px; }
  .case-step-title { font-size: 14px; }
}
</style>