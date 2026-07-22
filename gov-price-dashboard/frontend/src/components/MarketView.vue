<!--
  MarketView.vue (2026-07-21)
  /market 公开市场行情页 — 不鉴权,访客可直访
  品类 × 城市 热力图 + 跨城归一价格聚合
  数据源: /api/market/* (公开)
-->
<template>
  <div class="market">
    <!-- 顶栏 -->
    <header class="m-topbar">
      <a href="/home" class="m-brand">Pengfit · 材价通</a>
      <nav class="m-nav">
        <a href="/home">首页</a>
        <a href="/market" class="active">市场行情</a>
        <a href="/cockpit">控制台</a>
      </nav>
    </header>

    <main class="m-main">
      <!-- 主标题 -->
      <section class="m-hero">
        <h1>全国建材市场行情</h1>
        <p class="m-hero-sub">
          {{ overview.cities_count || '—' }} 城住建局官方数据 ·
          {{ overview.breeds_count?.toLocaleString() || '—' }} 跨城归一品类 ·
          实时聚合跨城材料价格涨跌
        </p>
        <p v-if="overview.latest_period_end" class="m-hero-meta">
          本期截止 {{ overview.latest_period_end }} · 对比 {{ overview.prev_period_end || '上期' }}
        </p>
      </section>

      <!-- KPI -->
      <section class="m-kpi">
        <div class="m-kpi-item">
          <div class="m-kpi-label">已覆盖城市</div>
          <div class="m-kpi-value">{{ overview.cities_count || '—' }}</div>
          <div class="m-kpi-sub">住建局官方</div>
        </div>
        <div class="m-kpi-item">
          <div class="m-kpi-label">跨城归一品类</div>
          <div class="m-kpi-value">{{ overview.breeds_count?.toLocaleString() || '—' }}</div>
          <div class="m-kpi-sub">统一口径对比</div>
        </div>
        <div class="m-kpi-item">
          <div class="m-kpi-label">本期均价变动</div>
          <div class="m-kpi-value" :class="changeClass(overview.overall_change_pct)">
            {{ formatPct(overview.overall_change_pct) }}
          </div>
          <div class="m-kpi-sub">vs 上一期</div>
        </div>
        <div class="m-kpi-item">
          <div class="m-kpi-label">价格数据条数</div>
          <div class="m-kpi-value">{{ (overview.total_records || 0).toLocaleString() }}</div>
          <div class="m-kpi-sub">DWS 消费层</div>
        </div>
      </section>

      <!-- 加载 / 错误 -->
      <div v-if="loading" class="m-loading">加载中…</div>
      <div v-else-if="loadError" class="m-error">⚠️ {{ loadError }}</div>

      <!-- (2026-07-21 删除涨跌榜:产品规格不同名称跨城对比意义不大) -->

      <!-- 热力图 -->
      <section class="m-card">
        <SectionHeader
          title="🌡️ 品类 × 城市 热力图"
          dot-color="blue"
          :subtitle="`行:归一种 · 列:已覆盖城市 · 色深:本期 vs 上期涨跌幅 (锁定规格后跨城可比)`"
        />

        <!-- 品种 + 规格 选择器 (参考 /trend 页 CustomSelect 风格) -->
        <div class="m-heatmap-selectors">
          <CustomSelect
            v-model="selectedBreed"
            :options="breedSelectOptions"
            placeholder="— 全部 (Top 15) —"
            :count-suffix="true"
            @change="onBreedChange"
          />
        </div>

        <!-- 属性自由组合(每个 k 的每个 v 独立可勾选,可单选/多选/跨维度组合) -->
        <div v-if="selectedBreed && attrKeys.length" class="m-attr-filters">
          <div class="m-attr-header">
            <span class="m-attr-header-label">
              属性自由组合(可单选 / 多选 / 跨维度组合)
              <span class="m-attr-header-count">{{ attrFilterTotal }} 个已选</span>
            </span>
            <button class="m-spec-link" @click="clearAttrFilters">清空所有</button>
          </div>
          <div v-for="k in attrKeys" :key="k.key" class="m-attr-row">
            <span class="m-attr-key-label" :title="k.key">{{ k.label || k.key }}</span>
            <div class="m-attr-values">
              <div
                v-for="v in k.values"
                :key="v.value"
                class="m-attr-chip"
                :class="{ active: isAttrSelected(k.key, v.value) }"
                :title="`${k.key}=${v.value} · ${v.docs} 条`"
                @click="toggleAttrValue(k.key, v.value)"
              >
                {{ v.value }}
                <span class="m-attr-chip-count">{{ v.docs }}</span>
              </div>
            </div>
          </div>
        </div>

        <button v-if="selectedBreed || attrFilterTotal" @click="resetSelection" class="m-reset-btn m-reset-btn-block">
          ↻ 重置
        </button>

        <!-- filter-meta 药丸状态条 -->
        <div class="m-heatmap-meta">
          <span class="m-meta-pill">
            🔍 品种: <strong>{{ selectedBreed || '全部 Top 15' }}</strong>
          </span>
          <span class="m-meta-pill">
            🎯 筛选: <strong>{{ attrFilterSummary || '无' }}</strong>
          </span>
          <span class="m-meta-pill">
            🌐 填充: <strong>{{ filledCells }} / {{ totalCells }}</strong> 格
            <span v-if="totalCells" class="m-meta-pct">({{ fillRate }}%)</span>
          </span>
        </div>

        <div
          v-if="heatmap.breeds.length && heatmap.cities.length"
          class="m-heatmap-scroll"
        >
          <div
            class="m-heatmap-grid"
            :style="heatmapGridStyle"
          >
            <!-- 表头 -->
            <div class="m-heatmap-cell m-heatmap-corner">品种 \ 城市</div>
            <div
              v-for="city in heatmap.cities"
              :key="'h' + city.key"
              class="m-heatmap-cell m-heatmap-th"
            >
              {{ city.label }}
            </div>
            <!-- 数据行 -->
            <template v-for="(breed, bi) in heatmap.breeds" :key="breed.breed + (breed.spec_fingerprint || '')">
              <div class="m-heatmap-cell m-heatmap-row-label">
                <div class="m-row-name">{{ breed.breed }}</div>
                <div class="m-row-meta">{{ breed.spec_label || breed.category_name_l3 || '—' }}</div>
              </div>
              <div
                v-for="(city, ci) in heatmap.cities"
                :key="breed.breed + '-' + city.key"
                class="m-heatmap-cell"
                :style="cellStyle(heatmap.matrix[bi]?.[ci])"
                :title="cellTitle(breed, city, heatmap.matrix[bi]?.[ci])"
              >
                {{ formatCell(heatmap.matrix[bi]?.[ci]) }}
              </div>
            </template>
          </div>
        </div>
        <div v-else class="m-empty">暂无热力图数据(可能数据尚未聚合)</div>
      </section>

      <!-- 数据说明 -->
      <footer class="m-footnote">
        <p>
          数据来源:各省/市住建局官方造价信息期刊 · 17 城 · 78 万条材料价格 · 9,931 个跨城归一品类
        </p>
        <p>
          「环比」取本期 vs 上一期(各城节奏不一,可能为月度/双月/季度);
          涨幅榜过滤掉 |变化率| &lt; 0.5% 的噪音;
          公开页所有数据均为聚合统计,不暴露单笔原始价格。
        </p>
        <p class="m-footnote-meta">
          © 2026 Pengfit OPC · 1 人 + AI &gt; 1 个团队
        </p>
      </footer>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import CustomSelect from './CustomSelect.vue'
import SectionHeader from './SectionHeader.vue'

const overview = ref({})
const heatmap = ref({ breeds: [], cities: [], matrix: [], spec_fingerprint: null })

// 热力图选择器状态
const selectedBreed = ref('')
const attrKeys = ref([])              // [{key, label, values: [{value, docs}], total_docs}, ...]  v0.2 (2026-07-22) 加 label
const attrFilters = ref({})          // {key: [values]} — 各 k 独立多选
const breedOptions = ref([])
const loadingAttrKeys = ref(false)

// 已选筛选统计
const attrFilterTotal = computed(() => {
  return Object.values(attrFilters.value).reduce((sum, vs) => sum + (vs?.length || 0), 0)
})
const attrFilterSummary = computed(() => {
  const parts = []
  for (const [k, vs] of Object.entries(attrFilters.value)) {
    if (vs && vs.length) parts.push(`${k}=${vs.join('/')}`)
  }
  return parts.join(' + ')
})

// /trend 风格的 CustomSelect options 映射
const breedSelectOptions = computed(() => {
  return breedOptions.value.map(b => ({
    key: b.breed,
    label: b.breed,
    count: b.records,
  }))
})

// filter-meta 药丸条用
const filledCells = computed(() => {
  if (!heatmap.value?.matrix) return 0
  let n = 0
  for (const row of heatmap.value.matrix) {
    for (const c of row) if (c != null) n++
  }
  return n
})
const totalCells = computed(() => {
  if (!heatmap.value?.breeds || !heatmap.value?.cities) return 0
  return heatmap.value.breeds.length * heatmap.value.cities.length
})
const fillRate = computed(() => {
  if (!totalCells.value) return 0
  return Math.round((filledCells.value / totalCells.value) * 100)
})

const loading = ref(true)
const loadError = ref('')

const heatmapGridStyle = computed(() => ({
  gridTemplateColumns: `180px repeat(${heatmap.value.cities?.length || 1}, minmax(64px, 1fr))`,
}))

async function fetchJson(path) {
  const r = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`)
  return r.json()
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const results = await Promise.allSettled([
      fetchJson('/api/market/overview'),
      fetchJson('/api/market/change-heatmap?top_n=15'),
    ])
    const [ov, hm] = results
    if (ov.status === 'fulfilled') overview.value = ov.value
    if (hm.status === 'fulfilled') {
      heatmap.value = hm.value || { breeds: [], cities: [], matrix: [], spec_fingerprint: null }
      // 把 top 15 breeds 同步给下拉选择器
      breedOptions.value = hm.value?.breeds || []
    }

    const failed = results.filter(r => r.status === 'rejected')
    if (failed.length === results.length) {
      loadError.value = '数据加载失败,请稍后重试'
    } else if (failed.length > 0) {
      console.warn('[market] 部分接口失败', failed)
    }
  } catch (e) {
    loadError.value = e?.message || '未知错误'
  } finally {
    loading.value = false
  }
}

// 选品种
async function onBreedChange() {
  attrFilters.value = {}
  attrKeys.value = []
  if (!selectedBreed.value) {
    await loadHeatmap()
    return
  }
  await loadAttrKeys()
  await loadHeatmap()
}

// 属性 k=v 独立勾选(可单选/多选/跨维度组合)
function toggleAttrValue(key, value) {
  if (!attrFilters.value[key]) attrFilters.value[key] = []
  const i = attrFilters.value[key].indexOf(value)
  if (i >= 0) {
    attrFilters.value[key].splice(i, 1)
    if (attrFilters.value[key].length === 0) delete attrFilters.value[key]
  } else {
    attrFilters.value[key].push(value)
  }
  // 触发响应式
  attrFilters.value = { ...attrFilters.value }
  loadHeatmap()
}
function isAttrSelected(key, value) {
  return !!(attrFilters.value[key] && attrFilters.value[key].includes(value))
}
function clearAttrFilters() {
  attrFilters.value = {}
  loadHeatmap()
}

// 重置
async function resetSelection() {
  selectedBreed.value = ''
  attrFilters.value = {}
  attrKeys.value = []
  await loadHeatmap()
}

async function loadAttrKeys() {
  if (!selectedBreed.value) return
  loadingAttrKeys.value = true
  try {
    const r = await fetchJson(
      `/api/market/attr-keys?breed=${encodeURIComponent(selectedBreed.value)}&limit_per_value=30`
    )
    attrKeys.value = r.data || []
  } catch (e) {
    console.error('[market] attr-keys 加载失败', e)
    attrKeys.value = []
  } finally {
    loadingAttrKeys.value = false
  }
}

async function loadHeatmap() {
  const params = []
  if (selectedBreed.value) {
    params.push(`breed=${encodeURIComponent(selectedBreed.value)}`)
  } else {
    params.push('top_n=15')
  }
  // attr_filters: 格式 k1:v1,v2;k2:v3 (AND 关系,各 k 至少 1 个匹配)
  const filterStr = Object.entries(attrFilters.value)
    .filter(([_, vs]) => vs && vs.length > 0)
    .map(([k, vs]) => `${k}:${vs.join(',')}`)
    .join(';')
  if (filterStr) {
    params.push(`attr_filters=${encodeURIComponent(filterStr)}`)
  }
  const url = '/api/market/change-heatmap?' + params.join('&')
  try {
    const r = await fetchJson(url)
    heatmap.value = r || { breeds: [], cities: [], matrix: [] }
  } catch (e) {
    console.error('[market] heatmap 加载失败', e)
  }
}

// 规格指纹: "diameter=20|grade=HRB400" → "diameter: 20 · grade: HRB400"
function formatFingerprint(fp) {
  if (!fp) return ''
  return fp.split('|').map(p => {
    const idx = p.indexOf('=')
    if (idx < 0) return p
    return `${p.substring(0, idx)}: ${p.substring(idx + 1)}`
  }).join(' · ')
}

// 短格式(给下拉): 超过 35 字符截断
function formatFingerprintShort(fp) {
  const s = formatFingerprint(fp)
  return s.length > 35 ? s.substring(0, 35) + '…' : s
}

onMounted(loadAll)

function formatPct(pct) {
  if (pct == null || pct === 0) return pct === 0 ? '0.00%' : '—'
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct}%`
}
function changeClass(pct) {
  if (pct == null) return ''
  if (pct > 0) return 'm-up'
  if (pct < 0) return 'm-down'
  return ''
}
function formatCell(v) {
  if (v == null) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v}`
}
function cellStyle(v) {
  if (v == null) return { background: '#f3f4f6', color: '#9ca3af' }
  const clamped = Math.max(-10, Math.min(10, v))
  const intensity = Math.abs(clamped) / 10
  if (v >= 0) {
    return {
      background: `rgba(220, 38, 38, ${(0.12 + intensity * 0.6).toFixed(2)})`,
      color: intensity > 0.45 ? '#fff' : '#7f1d1d',
    }
  }
  return {
    background: `rgba(22, 163, 74, ${(0.12 + intensity * 0.6).toFixed(2)})`,
    color: intensity > 0.45 ? '#fff' : '#14532d',
  }
}
function cellTitle(breed, city, v) {
  if (v == null) return `${breed.breed} · ${city.label}: 无本期数据`
  return `${breed.breed} · ${city.label}: ${v >= 0 ? '+' : ''}${v}%`
}
</script>

<style scoped>
.market {
  min-height: 100vh;
  background: #f9fafb;
  color: #111827;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}

/* ── 顶栏 ── */
.m-topbar {
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  padding: 14px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 10;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.02);
}
.m-brand {
  font-weight: 700;
  font-size: 16px;
  color: #1e40af;
  text-decoration: none;
  letter-spacing: 0.3px;
}
.m-nav { display: flex; gap: 28px; }
.m-nav a {
  color: #6b7280;
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: color 0.15s;
}
.m-nav a:hover { color: #1e40af; }
.m-nav a.active { color: #1e40af; font-weight: 600; }

/* ── 主容器 ── */
.m-main {
  max-width: 1280px;
  margin: 0 auto;
  padding: 32px;
}

/* ── 主标题 ── */
.m-hero { margin-bottom: 24px; }
.m-hero h1 {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 8px 0;
  color: #111827;
  letter-spacing: -0.5px;
}
.m-hero-sub {
  font-size: 14px;
  color: #6b7280;
  margin: 0 0 4px 0;
}
.m-hero-meta {
  font-size: 12px;
  color: #9ca3af;
  margin: 0;
}

/* ── KPI ── */
.m-kpi {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}
.m-kpi-item {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 20px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.m-kpi-item:hover {
  border-color: #d1d5db;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.m-kpi-label {
  font-size: 13px;
  color: #6b7280;
  margin-bottom: 8px;
  font-weight: 500;
}
.m-kpi-value {
  font-size: 28px;
  font-weight: 700;
  color: #111827;
  line-height: 1.2;
  font-feature-settings: "tnum";
}
.m-kpi-value.m-up { color: #dc2626; }
.m-kpi-value.m-down { color: #16a34a; }
.m-kpi-sub {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 6px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

/* ── 通用卡片 ── */
.m-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 20px;
  margin-bottom: 20px;
}
.m-card h2 {
  font-size: 18px;
  font-weight: 700;
  margin: 0 0 4px 0;
}
.m-subtitle {
  font-size: 12px;
  color: #9ca3af;
  margin: 0 0 16px 0;
}

/* (2026-07-21 热门品类 section 已删,对应 CSS 一并清理) */

/* ── 属性自由组合(k=v 独立勾选) ── */
.m-attr-filters {
  margin: 12px 0 16px;
  padding: 12px 14px;
  background: #f9fafb;
  border: 1px solid #f3f4f6;
  border-radius: 8px;
}
.m-attr-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}
.m-attr-header-label {
  font-size: 11px;
  font-weight: 700;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.m-attr-header-count {
  background: #1e40af;
  color: #fff;
  padding: 1px 8px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 700;
  font-family: ui-monospace, monospace;
  text-transform: none;
  letter-spacing: 0;
}
.m-attr-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.m-attr-key-label {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 12px;
  font-weight: 700;
  color: #1e40af;
  min-width: 100px;
  flex-shrink: 0;
}
.m-attr-values {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex: 1;
}
.m-attr-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #fff;
  border: 1.5px solid #e5e7eb;
  border-radius: 6px;
  padding: 3px 8px;
  font-size: 11px;
  cursor: pointer;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-weight: 600;
  color: #374151;
  transition: all 0.15s ease;
  user-select: none;
}
.m-attr-chip:hover {
  border-color: #93c5fd;
  background: #f0f9ff;
}
.m-attr-chip.active {
  background: #1e40af;
  color: #fff;
  border-color: #1e40af;
  box-shadow: 0 1px 3px rgba(30, 64, 175, 0.3);
}
.m-attr-chip.active .m-attr-chip-count {
  color: #bfdbfe;
}
.m-attr-chip-count {
  color: #9ca3af;
  font-size: 10px;
  font-weight: 500;
}
.m-spec-link {
  background: none;
  border: none;
  color: #3b82f6;
  font-size: 11px;
  cursor: pointer;
  font-family: inherit;
  padding: 2px 8px;
  font-weight: 600;
  border-radius: 4px;
  transition: all 0.15s;
}
.m-spec-link:hover {
  background: #dbeafe;
  color: #1e40af;
}
.m-reset-btn-block {
  display: block;
  width: 100%;
  margin-top: 8px;
  padding: 8px;
  text-align: center;
}

/* ── 热力图选择器 ── */
.m-heatmap-selectors {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  margin: 12px 0 16px;
  padding: 12px 14px;
  background: #f9fafb;
  border-radius: 8px;
  border: 1px solid #f3f4f6;
}
.m-selector {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 200px;
}
.m-selector label {
  font-size: 11px;
  font-weight: 700;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.4px;
}
.m-selector select {
  padding: 7px 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #fff;
  font-size: 13px;
  color: #111827;
  font-family: inherit;
  cursor: pointer;
  transition: border-color 0.15s;
}
.m-selector select:hover { border-color: #3b82f6; }
.m-selector select:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}
.m-selector select:disabled {
  background: #f3f4f6;
  color: #9ca3af;
  cursor: not-allowed;
}
.m-reset-btn {
  padding: 7px 14px;
  border: 1px solid #d1d5db;
  background: #fff;
  color: #6b7280;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
  transition: all 0.15s;
}
.m-reset-btn:hover {
  background: #f3f4f6;
  color: #111827;
  border-color: #9ca3af;
}
.m-coverage-badge {
  margin: 0 0 12px;
  padding: 6px 12px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  font-size: 12px;
  color: #1e40af;
  display: inline-block;
}
.m-coverage-badge code {
  background: #fff;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid #dbeafe;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 11px;
  color: #1e3a8a;
}

/* ── filter-meta 药丸状态条(/trend 页风格) ── */
.m-heatmap-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 12px 0 16px;
  padding: 0 4px;
}
.m-meta-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f3f4f6;
  color: #4b5563;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid #e5e7eb;
}
.m-meta-pill strong {
  color: #1e40af;
  font-weight: 700;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.m-meta-pct {
  color: #6b7280;
  font-size: 11px;
  font-weight: 500;
  margin-left: 2px;
}

/* ── 热力图 ── */
.m-heatmap-scroll {
  overflow-x: auto;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}
.m-heatmap-grid {
  display: grid;
  gap: 2px;
  background: #f3f4f6;
  min-width: 100%;
  font-size: 11px;
}
.m-heatmap-cell {
  background: #fff;
  padding: 6px 8px;
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  font-weight: 600;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.m-heatmap-corner {
  font-weight: 700;
  color: #6b7280;
  font-size: 10px;
  background: #f9fafb;
  justify-content: flex-start;
  padding-left: 12px;
}
.m-heatmap-th {
  font-size: 11px;
  color: #374151;
  font-weight: 500;
  background: #f9fafb;
}
.m-heatmap-row-label {
  flex-direction: column;
  align-items: flex-start;
  padding: 8px 12px;
  background: #f9fafb;
  min-width: 0;
}
.m-row-name {
  font-weight: 600;
  font-size: 12px;
  color: #111827;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: -apple-system, "PingFang SC", sans-serif;
}
.m-row-meta {
  font-size: 10px;
  color: #9ca3af;
  margin-top: 2px;
}
.m-empty {
  padding: 60px 20px;
  text-align: center;
  color: #9ca3af;
  background: #fafbfc;
  border: 1px dashed #e5e7eb;
  border-radius: 8px;
}

/* ── 加载 / 错误 ── */
.m-loading,
.m-error {
  text-align: center;
  padding: 20px;
  border-radius: 8px;
  margin-bottom: 16px;
}
.m-loading {
  background: #eff6ff;
  color: #1e40af;
  border: 1px solid #dbeafe;
}
.m-error {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

/* ── 脚注 ── */
.m-footnote {
  margin-top: 32px;
  padding-top: 20px;
  border-top: 1px solid #e5e7eb;
  color: #9ca3af;
  font-size: 12px;
  text-align: center;
  line-height: 1.7;
}
.m-footnote p { margin: 4px 0; }
.m-footnote-meta {
  margin-top: 12px !important;
  font-size: 11px;
  opacity: 0.7;
}

/* ── 响应式 ── */
@media (max-width: 980px) {
  .m-kpi { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
  .m-main { padding: 20px 16px; }
  .m-topbar { padding: 12px 16px; }
  .m-nav { gap: 16px; }
  .m-kpi { grid-template-columns: 1fr; }
  .m-hero h1 { font-size: 22px; }
}
</style>