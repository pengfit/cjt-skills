<!--
  MarketView.vue (2026-07-28 v1.0 重写)
  /market 公开市场行情页 — 不鉴权,访客可直访

  v1.0 改造 (2026-07-28):
    - 删除热力图(原跨区域比价功能)—道友需求 1
    - 浏览器 GPS 定位 → 所在省份 → 半年价格趋势折线图(单图 10 品种)—道友需求 2
    - 默认 10 个随机品种(取自所在省份 NORM 池)—道友需求 3
    - 拒绝/失败定位时,显示省份选择器 dropdown 兜底
  数据源: /api/market/* (公开)
-->
<template>
  <div class="market">
    <!-- 阅读进度条 -->
    <div class="read-progress" :style="{ width: readProgress + '%' }"></div>

    <!-- 顶栏 -->
    <header class="m-topbar">
      <a href="/home" class="m-brand">Pengfit · ChinaJT</a>
      <nav class="m-nav">
        <a href="/home">首页</a>
        <a href="/market" class="active">市场行情</a>
        <a href="/cockpit">控制台</a>
      </nav>
    </header>

    <main class="m-main">
      <!-- 主标题 -->
      <section class="m-hero">
        <h1>{{ userProvince ? `${userProvince} · 建材市场行情` : '全国建材市场行情' }}</h1>
        <p class="m-hero-sub">
          {{ overview.cities_count || '—' }} 城住建局官方数据 ·
          {{ overview.breeds_count?.toLocaleString() || '—' }} 跨城归一品类 ·
          半年价格趋势跟踪
        </p>
        <p v-if="overview.latest_period_end" class="m-hero-meta">
          本期截止 {{ overview.latest_period_end }} · 对比 {{ overview.prev_period_end || '上期' }}
        </p>

        <!-- 2026-07-28: 定位状态条 — dropdown 永远可见,用户随时能切地区 -->
        <div class="m-geo-bar">
          <span class="m-geo-status" :class="`m-geo-${geoStatus}`">
            <span class="m-geo-icon">📍</span>
            <span class="m-geo-status-text">
              <template v-if="geoStatus === 'prompting'">准备定位</template>
              <template v-else-if="geoStatus === 'locating'">定位中…</template>
              <template v-else-if="geoStatus === 'located'">
                当前地区
                <span v-if="geoSource === 'cache'" class="m-geo-source">(本地缓存)</span>
                <span v-else-if="geoSource === 'manual'" class="m-geo-source">(手动)</span>
              </template>
              <template v-else-if="geoStatus === 'denied'">定位未授权 · 选择地区</template>
              <template v-else-if="geoStatus === 'unsupported'">浏览器不支持定位 · 选择地区</template>
              <template v-else-if="geoStatus === 'error'">定位失败 · 选择地区</template>
            </span>

            <!-- 地区切换 dropdown:永远可见,定位中禁用(避免定位结果覆盖用户选择) -->
            <select
              v-model="userProvince"
              class="m-geo-select"
              :disabled="geoStatus === 'prompting' || geoStatus === 'locating'"
              @change="onProvinceSelect"
              title="切换地区"
            >
              <option value="">全国</option>
              <option v-for="p in availableProvinces" :key="p" :value="p">{{ p }}</option>
            </select>

            <!-- 重新定位/重试按钮:定位中不显示(避免重复请求) -->
            <button
              v-if="geoStatus !== 'prompting' && geoStatus !== 'locating'"
              class="m-geo-reset"
              type="button"
              @click="resetGeo"
              :title="geoStatus === 'located' ? '重新请求浏览器定位' : '重试定位'"
            >
              ↻ {{ geoStatus === 'located' ? '重新定位' : '重试' }}
            </button>
          </span>
        </div>
      </section>

      <!-- 加载 / 错误 -->
      <div v-if="loading" class="m-loading">加载中…</div>
      <div v-else-if="loadError" class="m-error">⚠️ {{ loadError }}</div>

      <!-- 2026-07-28 v3.1: /market 嵌 2 张真卡片 — 价格走势 + 时序数据表 (仿 /trend 页) -->
      <!-- 卡片 1：价格走势 多线折线图 — top 8 品种 × top 3 规格 × N 期 (N 由 toolbar 选) -->
      <section v-if="trendCard.data?.series?.length || trendCard.loading" class="m-card m-trend-chart-card">
        <header class="m-card-head">
          <div class="m-trend-chart-info">
            <h2 class="m-trend-chart-title">📈 价格走势 · {{ trendCard.cityLabel }}</h2>
          </div>
          <!-- 2026-07-28 v3.1: toolbar — 城市下拉 + 期数下拉 + 品种输入框搜索 -->
          <div class="m-trend-toolbar">
            <select v-model="trendCard.cityKey" class="m-trend-select" :disabled="trendCard.citiesLoading" @change="onTrendCityChange">
              <option v-if="trendCard.citiesLoading" value="">加载城市中…</option>
              <option v-for="c in (trendCard.cities || [])" :key="c.key" :value="c.key">{{ c.label }}</option>
            </select>
            <select v-model="trendCard.periodsLimit" class="m-trend-select" @change="onTrendFilterChange">
              <option v-for="p in trendPeriodOptions" :key="p.v" :value="p.v">{{ p.label }}</option>
            </select>
            <div class="m-trend-search-wrap">
              <input
                v-model="trendCard.searchQuery"
                type="text"
                class="m-trend-search-input"
                placeholder="🔍 输入品种名 (例:HRB400) 回车搜索"
                @keydown.enter="onTrendSearchEnter"
              />
              <button
                v-if="trendCard.searchQuery"
                class="m-trend-search-clear"
                type="button"
                @click="clearTrendSearchInput"
                title="清空输入框"
              >×</button>
            </div>
            <button
              v-if="trendCard.selectedBreeds.length"
              class="m-trend-refresh-btn"
              type="button"
              @click="resetBreedSelection"
              :title="`清空 ${trendCard.selectedBreeds.length} 个已选品种 — 回到随机 top 8`"
            >
              🎲 重选 ({{ trendCard.selectedBreeds.length }})
            </button>
            <div v-if="trendCard.searchError" class="m-trend-search-error">
              {{ trendCard.searchError }}
            </div>
          </div>
        </header>
        <div ref="trendChartEl" class="m-trend-chart"></div>
        <div v-if="trendCard.loading && !trendCard.data?.series?.length" class="m-trend-status">加载中…</div>
        <div v-if="!trendCard.loading && !trendCard.data?.series?.length" class="m-trend-status">
          该城市暂无趋势数据
        </div>
      </section>

      <!-- 卡片 2：时序数据表 — 每品种 × 每规格 × 每期均价 -->
      <section v-if="trendTable.rows.length || trendCard.loading" class="m-card m-trend-table-card">
        <header class="m-card-head">
          <div>
            <h2 class="m-trend-chart-title">📊 时序数据表 · 按规格拆分</h2>
            <p class="m-trend-chart-sub">
              共 {{ trendTable.rows.length }} 条规格行 ·
              同材料不同规格价差可达数百倍，已拆分展示 ·
              「环比」取首末两期
            </p>
          </div>
        </header>
        <div class="m-trend-table-scroll">
          <table class="m-trend-table">
            <thead>
              <tr>
                <th>材料</th>
                <th>规格</th>
                <th>单位</th>
                <th v-for="p in trendTable.periods" :key="p.start" :title="`${p.start} ~ ${p.end}`">
                  {{ p.label }}
                </th>
                <th class="m-trend-th-trend">环比</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in trendTable.rows" :key="`${r.material}__${r.spec}`">
                <td class="m-trend-cell-material">{{ r.material }}</td>
                <td class="m-trend-cell-spec" :title="r.spec">{{ r.spec }}</td>
                <td class="m-trend-cell-unit">{{ r.unit || '—' }}</td>
                <td v-for="p in trendTable.periods" :key="p.start" class="m-trend-cell-price">
                  <template v-if="r.prices[p.start] != null">
                    <div class="m-trend-price-val">{{ r.prices[p.start].toFixed(2) }}</div>
                    <div class="m-trend-price-meta">{{ r.pricesN[p.start] }}条</div>
                  </template>
                  <span v-else class="m-trend-no-data">—</span>
                </td>
                <td class="m-trend-cell-trend">
                  <template v-if="r.trendPct != null">
                    <div :class="['m-trend-pct', trendClassOf(r.trendPct, r.trendAbs)]">
                      {{ r.trendPct >= 0 ? '↑' : '↓' }} {{ Math.abs(r.trendPct).toFixed(1) }}%
                    </div>
                    <div class="m-trend-abs">
                      {{ r.trendAbs >= 0 ? '+' : '' }}{{ r.trendAbs.toFixed(1) }}
                    </div>
                  </template>
                  <span v-else class="m-trend-no-data">—</span>
                </td>
              </tr>
              <tr v-if="!trendTable.rows.length && !trendCard.loading">
                <td :colspan="trendTable.periods.length + 4" class="m-trend-no-data" style="padding: 30px;">
                  暂无数据
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- KPI -->
      <section class="m-kpi" ref="kpiRef">
        <div class="m-kpi-item">
          <div class="m-kpi-label">已覆盖城市</div>
          <div class="m-kpi-value">
            <span class="kpi-number" :data-target="overview.cities_count || 0">{{ formatKpi(overview.cities_count, 0) }}</span>
            <span class="m-kpi-suffix">城</span>
          </div>
          <div class="m-kpi-sub">住建局官方</div>
        </div>
        <div class="m-kpi-item">
          <div class="m-kpi-label">跨城归一品类</div>
          <div class="m-kpi-value">
            <span class="kpi-number" :data-target="overview.breeds_count || 0">{{ formatKpi(overview.breeds_count, 0) }}</span>
            <span class="m-kpi-suffix">个</span>
          </div>
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
          <div class="m-kpi-value">
            <span class="kpi-number" :data-target="overview.total_records || 0">{{ (overview.total_records || 0).toLocaleString() }}</span>
            <span class="m-kpi-suffix">条</span>
          </div>
          <div class="m-kpi-sub">跨城聚合</div>
        </div>
      </section>

      <!-- 2026-07-28: 数据来源 + 新鲜度 合并卡(原数据治理透明卡 + 数据来源)— 每个省/市一卡,点进住建局 -->
      <section class="m-card m-card-quality" v-if="mergedCities.length">
        <header class="m-quality-toolbar">
          <div class="m-quality-toolbar-info">
            <h2 class="m-quality-title">📊 数据来源与新鲜度</h2>
            <p class="m-quality-toolbar-sub">
              {{ mergedCities.length }} 城 · 点击进入各省/市住建局官方期刊 ·
              🟢 ≤90d · 🟡 90-180d · 🔴 ≥180d · 按新鲜度倒序(异常在前)
            </p>
          </div>
        </header>
        <div class="m-quality-grid">
          <a
            v-for="c in mergedCities"
            :key="c.key"
            :href="c.site_url || '#'"
            :target="c.site_url ? '_blank' : undefined"
            rel="noopener noreferrer"
            class="m-quality-card"
            :class="[`m-quality-${c.tone}`, c.site_url ? 'm-quality-link' : 'm-quality-nolink']"
            :title="`${c.label} · ${c.province || ''} · ${c.docs.toLocaleString()} 文档 · 最新期 ${c.latest_end || '—'}${c.site_url ? ' · 点击进入住建局' : ''}`"
          >
            <span class="m-quality-emoji">{{ c.emoji }}</span>
            <div class="m-quality-info">
              <div class="m-quality-row1">
                <span class="m-quality-label">{{ c.label }}</span>
                <span class="m-quality-province" v-if="c.province">{{ c.province }}</span>
                <span class="m-quality-arrow" v-if="c.site_url">↗</span>
              </div>
              <div class="m-quality-row2">
                <span class="m-quality-age">{{ c.age_days < 0 ? '?' : c.age_days }}d</span>
                <span class="m-quality-sep">·</span>
                <span class="m-quality-date">{{ c.latest_end || '—' }}</span>
                <span class="m-quality-sep">·</span>
                <span class="m-quality-docs">{{ formatNumber(c.docs) }} 文档</span>
              </div>
            </div>
          </a>
        </div>
      </section>

      <!-- 回到顶部 -->
      <div class="m-back-to-top-wrap">
        <button class="m-back-to-top" type="button" @click="scrollToTop" aria-label="回到顶部">↑ 回到顶部</button>
      </div>

      <!-- 数据说明 -->
      <footer class="m-footnote">
        <p>
          数据来源:各省/市住建局官方造价信息期刊 ·
          <strong>{{ overview.cities_count || 0 }} 城</strong> ·
          {{ (overview.total_records || 0).toLocaleString() }} 条材料价格 ·
          {{ (overview.breeds_count || 0).toLocaleString() }} 个跨城归一品类
          <span v-if="overview.cities_count && overview.cities_count < 17" class="m-footnote-warn">
            · ⚠️ 当前仅 {{ overview.cities_count }} 城完成 ETL,其余城市数据收集中
          </span>
        </p>
        <p>
          定位服务采用浏览器 GPS + OpenStreetMap Nominatim 反向地理编码(本地缓存 24h);
          若浏览器拒绝定位或不支持,可手动选择省份;
          「环比」取本期 vs 上一期(各城节奏不一,可能为月度/双月/季度);
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
import { ref, computed, reactive, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useHead } from '@unhead/vue'
import { useEcharts } from '../composables/useEcharts'
// 2026-07-28 v2: 重加 useEcharts — /market 嵌入价格走势 + 时序数据表 2 张卡片需要 echarts
//   (不再需 registerGovPriceTheme / GOV_PRICE_PALETTE,内联颜色池足够)

// SEO: /market 页面级 head — 长尾词关键词
const SITE_URL = 'https://pengfit.cn'
useHead({
  title: '材料价格行情 · 钢筋/水泥/给水管/电缆 跨城实时价格 · ChinaJT',
  meta: [
    { name: 'description', content: '全国 20 城建材市场行情 · 钢筋 / 水泥 / 给水管 / 电缆 等工程造价材料跨城归一价格 · 住建局官方期刊 · 公开免费 · ChinaJT cjt-skills' },
    { name: 'keywords', content: '材料价格行情, 钢筋价格, 水泥价格, 给水管价格, 电缆价格, 建材市场, 工程造价, 跨城价格对比, 涨跌幅, 住建局, ChinaJT, cjt-skills' },
    { property: 'og:title', content: '材料价格行情 · 钢筋/水泥/给水管/电缆 跨城实时价格 · ChinaJT' },
    { property: 'og:description', content: '全国 20 城住建局官方造价信息 · 钢筋/水泥/给水管/电缆跨城归一价格 · 涨跌幅追踪' },
    { property: 'og:url', content: `${SITE_URL}/market` },
    { property: 'og:type', content: 'website' },
    { property: 'og:image', content: `${SITE_URL}/og-image.png` },
    { name: 'twitter:title', content: '材料价格行情 · 钢筋/水泥/给水管/电缆 跨城实时价格' },
    { name: 'twitter:description', content: '全国 20 城住建局官方造价信息 · 钢筋/水泥/给水管/电缆跨城归一价格 · 涨跌幅追踪' },
    { name: 'twitter:image', content: `${SITE_URL}/og-image.png` },
  ],
  link: [
    { rel: 'canonical', href: `${SITE_URL}/market` },
  ],
  script: [
    {
      type: 'application/ld+json',
      innerHTML: JSON.stringify({
        '@context': 'https://schema.org',
        '@type': 'Dataset',
        name: 'ChinaJT · 工程材料价格数据 · 17 城住建局官方期刊',
        description: '17 城住建局官方造价信息期刊数据 · 跨城归一品类 9,000+ · 钢筋 / 水泥 / 给水管 / 电缆 等材料价格行情',
        url: `${SITE_URL}/market`,
        inLanguage: 'zh-CN',
        license: 'https://opensource.org/licenses/MIT',
        isAccessibleForFree: true,
        keywords: ['工程造价', '材料价格', '钢筋价格', '水泥价格', '给水管价格', '电缆价格', '住建局', '政府数据', '跨城归一'],
        spatialCoverage: { '@type': 'Place', name: '中华人民共和国' },
        temporalCoverage: '2024-01-01/..',
        provider: {
          '@type': 'Organization',
          name: 'Pengfit',
          url: 'https://github.com/pengfit/cjt-skills',
        },
        publisher: { '@id': `${SITE_URL}/#organization` },
        distribution: {
          '@type': 'DataDownload',
          encodingFormat: 'application/json',
          contentUrl: `${SITE_URL}/api/market/overview`,
          license: 'https://opensource.org/licenses/MIT',
        },
      }),
    },
  ],
})

// ── Cache buster ──────────────────────────────────────────────────
const route = useRoute()
const cacheVersion = computed(() => {
  const v = route.query.v
  return v && String(v).trim() ? String(v).trim() : ''
})

function withCacheBuster(path) {
  if (!cacheVersion.value) return path
  return path.includes('?') ? `${path}&v=${cacheVersion.value}` : `${path}?v=${cacheVersion.value}`
}

// ── 状态 ──────────────────────────────────────────────────
const overview = ref({})
const sources = ref({ total_skills: 0, total_cities: 0, sources: [] })
const quality = ref({ cities: [] })

// 浏览器定位 + 省份
// geoStatus: 'prompting' | 'locating' | 'located' | 'denied' | 'unsupported' | 'error'
const userProvince = ref('')  // '' = 全国
const geoStatus = ref('prompting')
const geoSource = ref('')  // 'gps' | 'cache' | 'manual'
const availableProvinces = ref([])  // 从 data-quality 推 — 不需新端点

// 半年价格趋势(2026-07-28 整段删除 — 功能已迁移到 /trend 页,MarketView 不再持有趋势状态)
//   删除清单:
//     provinceTrend / trendChartRef / trendChart / trendLoading / refreshingBreeds
//     selectedBreeds / breedSearch / breedSearchResults / breedSearchLoading / breedSearchOpen / breedSearchTimer
//     _onDocMousedown / registerGovPriceThemeOnce
//     onBreedSearchInput / searchBreeds / addBreedFromSearch / onBreedSearchEnter
//     loadProvinceTrend / refreshRandomBreeds / renderTrendChart
//     watch(userProvince, ...) / onMounted 的 loadProvinceTrend / onUnmounted 的 dispose

const loading = ref(true)
const loadError = ref('')

// ── fetch helper ──────────────────────────────────────────────────
async function fetchJson(path) {
  // 公开页守卫: /market 只能调 /api/market/* 和 /api/norm/price-trend (后者由后端 _PUBLIC_PATHS 放开)
  if (!path.startsWith('/api/market/') && !path.startsWith('/api/norm/')) {
    throw new Error(`[market-view-guard] /market 页面禁止调用 ${path}\n允许范围: /api/market/* /api/norm/*`)
  }
  const finalPath = withCacheBuster(path)
  const r = await fetch(finalPath, { headers: { Accept: 'application/json' } })
  if (!r.ok) throw new Error(`${finalPath} → HTTP ${r.status}`)
  return r.json()
}

// ── 数据加载 ──────────────────────────────────────────────────
async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    // 公开页并发拉 overview / sources / data-quality(后者用来推 availableProvinces)
    const [ov, src, qu] = await Promise.allSettled([
      fetchJson('/api/market/overview'),
      fetchJson('/api/market/sources'),
      fetchJson('/api/market/data-quality'),
    ])
    if (ov.status === 'fulfilled') {
      overview.value = ov.value
    } else {
      console.warn('[market] overview 加载失败', ov.reason)
      loadError.value = '数据加载失败，请稍后重试'
    }
    if (src.status === 'fulfilled') {
      sources.value = src.value
    } else {
      console.warn('[market] sources 加载失败', src.reason)
    }
    if (qu.status === 'fulfilled') {
      quality.value = qu.value
      // 从 data-quality 推 availableProvinces(去重 + 排序)
      const provs = [...new Set(qu.value.cities.map(c => c.province).filter(Boolean))]
      availableProvinces.value = provs.sort((a, b) => a.localeCompare(b, 'zh-CN'))
    } else {
      console.warn('[market] data-quality 加载失败', qu.reason)
    }
  } catch (e) {
    loadError.value = e?.message || '未知错误'
  } finally {
    loading.value = false
  }
}

// 2026-07-28: 数据来源 + 新鲜度 合并 — quality.cities 按 key 拼 sources.site_url
const mergedCities = computed(() => {
  const sourcesByKey = {}
  for (const sk of sources.value.sources || []) {
    sourcesByKey[sk.key] = sk
  }
  return (quality.value.cities || []).map(c => ({
    ...c,
    site_url: sourcesByKey[c.key]?.site_url || null,
  }))
})

// 千/万格式化(给质量卡片的文档数用)
function formatNumber(n) {
  if (n == null) return '—'
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return Math.round(n).toString()
}

// ── 浏览器定位流程 ──────────────────────────────────────────────────
const GEO_CACHE_KEY = 'geo_province_v1'

async function requestGeoLocation() {
  // 检查浏览器支持
  if (!('geolocation' in navigator)) {
    geoStatus.value = 'unsupported'
    return
  }
  geoStatus.value = 'locating'

  // 优先读 localStorage 缓存(24h 内有效)
  try {
    const cached = localStorage.getItem(GEO_CACHE_KEY)
    if (cached) {
      const parsed = JSON.parse(cached)
      // 缓存过期(24h)或 province 字段缺失 → 当作无效
      if (parsed.province && parsed.at && (Date.now() - parsed.at) < 86400000) {
        userProvince.value = parsed.province
        geoSource.value = 'cache'
        geoStatus.value = 'located'
        return
      }
    }
  } catch (e) {
    console.warn('[geo] cache read fail', e)
  }

  // 调浏览器 GPS
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      try {
        const r = await fetchJson(
          `/api/market/geo-locate?lat=${pos.coords.latitude}&lng=${pos.coords.longitude}`
        )
        if (r.province) {
          userProvince.value = r.province
          geoSource.value = 'gps'
          geoStatus.value = 'located'
          localStorage.setItem(GEO_CACHE_KEY, JSON.stringify({
            province: r.province,
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            at: Date.now(),
          }))
        } else {
          // Nominatim 没识别到省(国外/海洋)
          geoStatus.value = 'error'
        }
      } catch (e) {
        console.warn('[geo] geo-locate 失败', e)
        geoStatus.value = 'error'
      }
    },
    (err) => {
      console.warn('[geo] geolocation 失败', err.code, err.message)
      geoStatus.value = err.code === err.PERMISSION_DENIED ? 'denied' : 'error'
    },
    { timeout: 10000, maximumAge: 3600000 }  // 10s 超时, 1h 内复用浏览器缓存
  )
}

function resetGeo() {
  localStorage.removeItem(GEO_CACHE_KEY)
  geoSource.value = ''
  requestGeoLocation()
}

function onProvinceSelect() {
  // 用户手动选了省份 — 也写 cache,避免下次再问 GPS
  if (userProvince.value) {
    geoSource.value = 'manual'
    localStorage.setItem(GEO_CACHE_KEY, JSON.stringify({
      province: userProvince.value,
      manual: true,
      at: Date.now(),
    }))
  }
}

// ── 半年价格趋势(2026-07-28 整段删除 — 已迁移到 /trend 页) ──────────────────────────────────────
//   删除清单:
//     onBreedSearchInput / searchBreeds / addBreedFromSearch / onBreedSearchEnter
//     loadProvinceTrend / refreshRandomBreeds / renderTrendChart
//     watch(userProvince, ...) / onMounted 的 loadProvinceTrend / onUnmounted 的 dispose

// ── 价格走势 + 时序数据表(2026-07-28 v3.3 — /market 嵌 /trend 双卡片 + toolbar) ──────────────────────
//   数据源: /api/market/price-trend + /api/market/trend-table (公开, 2026-07-28 v3 新增)
//   toolbar: 城市下拉 + 期数下拉 + 品种输入框 (仿 /trend 页交互)
//   v3.3: 输入框回车搜索 — 页面同步刷新, 只保留搜索后的品种数据, 清旧数据
//   默认参数: city=qingdao (NORM 索引已 ETL), 近 6 期 (v3.2 默认收紧), top 8 品种, top 3 规格
const trendCard = reactive({
  data: null,
  loading: false,
  cityLabel: '青岛',  // 默认; 响应返回后覆盖
  cityKey: 'qingdao',
  cities: [],           // /api/market/cities 返回 (按 docs_count 倒序)
  citiesLoading: false,
  periodsLimit: '6',    // v3.2: 默认近 6 期 (之前是 12); '6' | '12' | '18' | '24'
  searchQuery: '',      // 品种输入框
  searchError: '',      // 搜索错误提示(未找到品种等)
  selectedBreeds: [],   // 用户显式选择的品种 (v3.3: 1 个 — 搜索后 只留这个品种)
})
const trendPeriodOptions = [
  { v: '6',  label: '近 6 期' },
  { v: '12', label: '近 12 期' },
  { v: '18', label: '近 18 期' },
  { v: '24', label: '近 24 期' },
]
const trendChartEl = ref(null)
let trendChartInstance = null
let _trendSearchTimer = null
const trendTable = reactive({
  periods: [],
  rows: [],
})

// 趋势阈值(与 /trend 页一致) — 强信号/弱信号/持平 三档
const TREND_THRESHOLD = {
  strong_pct: 5.0,   // |Δ%| ≥ 5% 视为强信号
  strong_abs: 30,    // |Δ元| ≥ 30 视为强信号
  mild_pct: 2.0,     // |Δ%| ≥ 2% 视为弱信号
  mild_abs: 10,      // |Δ元| ≥ 10 视为弱信号
}

function trendClassOf(pct, abs) {
  if (pct == null) return ''
  const dir = pct >= 0 ? 'up' : 'down'
  const strong = Math.abs(pct) >= TREND_THRESHOLD.strong_pct
                 || Math.abs(abs || 0) >= TREND_THRESHOLD.strong_abs
  const mild = Math.abs(pct) >= TREND_THRESHOLD.mild_pct
                 || Math.abs(abs || 0) >= TREND_THRESHOLD.mild_abs
  if (strong) return `m-trend-strong m-trend-${dir}`
  if (mild) return `m-trend-mild m-trend-${dir}`
  return 'm-trend-flat'
}

async function loadTrendCards() {
  trendCard.loading = true
  try {
    // 2026-07-28 v3: 改调 /api/market/price-trend + /api/market/trend-table
    //   不再复用 /api/norm/price-trend (那是 /trend 页专用,鉴权后访问)
    const commonParams = new URLSearchParams()
    commonParams.set('city', trendCard.cityKey)
    commonParams.set('periods', trendCard.periodsLimit)
    commonParams.set('top_specs', '3')
    commonParams.set('max_breeds', '8')
    // v3.1: 用户选了品种 → 后端按用户顺序返 (不随机 top 8)
    if (trendCard.selectedBreeds.length > 0) {
      commonParams.set('materials', trendCard.selectedBreeds.join(','))
    }
    // 双端点并发拉,后端复用同一份 ES 数据,前端各吃各的 shape
    const [chartR, tableR] = await Promise.all([
      fetchJson(`/api/market/price-trend?${commonParams.toString()}`),
      fetchJson(`/api/market/trend-table?${commonParams.toString()}`),
    ])
    if (!chartR.ok) {
      console.warn('[market-trend]', chartR.error)
      trendCard.data = { series: [], periods: [], total_docs: 0 }
      trendTable.rows = []
      trendTable.periods = []
      return
    }
    trendCard.data = chartR
    trendCard.cityLabel = chartR.label || trendCard.cityLabel
    trendTable.periods = chartR.periods || []

    // tableR 已后端预处理好(rows + prices + trend_pct/trend_abs),前端只适配字段名
    if (tableR.ok) {
      trendTable.rows = (tableR.rows || []).map(r => ({
        material: r.material,
        spec: r.spec,
        unit: r.unit,
        prices: r.prices || {},
        pricesN: r.prices_n || {},
        trendPct: r.trend_pct,
        trendAbs: r.trend_abs,
      }))
      // totalSpecs = 后端返回的 rows 数
      trendCard.totalSpecs = trendTable.rows.length
    } else {
      trendTable.rows = []
      trendCard.totalSpecs = 0
    }

    await nextTick()
    await renderTrendChart()
  } catch (e) {
    console.error('[market-trend]', e)
    trendCard.data = { series: [], periods: [], total_docs: 0 }
    trendTable.rows = []
    trendTable.periods = []
  } finally {
    trendCard.loading = false
  }
}

// ── 2026-07-28 v3.1: toolbar 交互 ──────────────────────────────────────
// 加载城市列表 (进页面首次拉)
//   v3.2: 传 userProvince 参数,后端只返该省 NORM 城市; 该省无 NORM 时 fallback 全国
async function loadMarketCities() {
  trendCard.citiesLoading = true
  try {
    const params = new URLSearchParams()
    if (userProvince.value) params.set('province', userProvince.value)
    let r = await fetchJson(`/api/market/cities?${params.toString()}`)
    // 该省无 NORM 数据 → fallback 全国(避免空下拉 + 默认青岛不在列里)
    if ((!r.cities || r.cities.length === 0) && userProvince.value) {
      console.warn(`[market-cities] ${userProvince.value} 无 NORM 城市, fallback 全国`)
      r = await fetchJson('/api/market/cities')
    }
    if (r.ok && r.cities) {
      trendCard.cities = r.cities
      const cur = trendCard.cities.find(c => c.key === trendCard.cityKey)
      if (cur) trendCard.cityLabel = cur.label
    }
  } catch (e) {
    console.warn('[market-cities]', e)
  } finally {
    trendCard.citiesLoading = false
  }
}

// 城市变更 → 重拉 (可能城市无 NORM 数据, 后端返 ok=False)
function onTrendCityChange() {
  const cur = trendCard.cities.find(c => c.key === trendCard.cityKey)
  if (cur) trendCard.cityLabel = cur.label
  loadTrendCards()
}

// 期数变更 → 重拉
function onTrendFilterChange() {
  loadTrendCards()
}

// 品种输入框 → 回车提交, 页面同步刷新(清旧数据, 只留搜索后的品种)
async function onTrendSearchEnter() {
  const q = trendCard.searchQuery.trim()
  if (!q) return
  trendCard.searchError = ''
  // 用 /api/market/breed-search 验证品种存在 + 拿到归一名字
  // 然后设 selectedBreeds = [normalized_breed], loadTrendCards 走 materials= 路径
  try {
    const params = new URLSearchParams()
    params.set('q', q)
    params.set('limit', '5')
    if (trendCard.cityKey) params.set('city', trendCard.cityKey)
    const data = await fetchJson(`/api/market/breed-search?${params.toString()}`)
    const results = data.results || []
    if (results.length === 0) {
      trendCard.searchError = `未找到品种 "${q}"`
      return
    }
    // 客户端排序:exact > prefix > contains > 其他
    const qLower = q.toLowerCase()
    const scored = results.map(r => {
      const name = r.breed.toLowerCase()
      let score = 3
      if (name === qLower) score = 0
      else if (name.startsWith(qLower)) score = 1
      else if (name.includes(qLower)) score = 2
      return { r, score }
    })
    scored.sort((a, b) => a.score - b.score || (b.r.records || 0) - (a.r.records || 0))
    const best = scored[0].r
    // 清旧数据, 只留这一个品种
    trendCard.selectedBreeds = [best.breed]
    await loadTrendCards()
  } catch (e) {
    trendCard.searchError = `搜索失败: ${e.message}`
  }
}

function clearTrendSearchInput() {
  trendCard.searchQuery = ''
  trendCard.searchError = ''
}

function resetBreedSelection() {
  trendCard.selectedBreeds = []
  trendCard.searchQuery = ''
  trendCard.searchError = ''
  loadTrendCards()
}

// 2026-07-28 v3.2: 当前地区 userProvince 变动 → 联动查询
//   1) loadMarketCities(按新省份过滤, fallback 全国)
//   2) 同步 cityKey — 若当前不在新城市列表里, 切到列表中第一个
//   3) loadTrendCards(重拉价格走势 + 时序数据表)
watch(userProvince, async (newP, oldP) => {
  if (newP === oldP) return
  await loadMarketCities()
  // 同步 cityKey — 若当前 cityKey 不在新城市列表里, 切到第一个
  if (trendCard.cities.length > 0) {
    const exists = trendCard.cities.find(c => c.key === trendCard.cityKey)
    if (!exists) {
      const first = trendCard.cities[0]
      trendCard.cityKey = first.key
      trendCard.cityLabel = first.label
    }
  }
  await loadTrendCards()
})

// 文档点击关闭品种搜索 dropdown(搜索框内点击不算)
function _onTrendDocMousedown(e) {
  const wrap = document.querySelector('.m-trend-search-wrap')
  if (wrap && wrap.contains(e.target)) return
  trendCard.searchOpen = false
}

const COLOR_POOL = [
  '#dc2626', '#2563eb', '#16a34a', '#ea580c', '#7c3aed',
  '#0891b2', '#db2777', '#65a30d', '#9333ea', '#0d9488',
  '#e11d48', '#4f46e5', '#059669', '#d97706', '#a21caf',
  '#b45309', '#0369a1', '#15803d', '#a16207',
]

async function renderTrendChart() {
  if (!trendChartEl.value) return
  const echarts = await useEcharts()
  if (!trendChartInstance) {
    trendChartInstance = echarts.init(trendChartEl.value, null, { renderer: 'canvas' })
  }
  const data = trendCard.data
  if (!data?.series?.length) {
    trendChartInstance.clear()
    return
  }
  const periods = data.periods || []
  const periodLabels = periods.map(p => p.label)
  const series = []
  let colorIdx = 0
  for (const s of data.series) {
    for (const sp of (s.specs || [])) {
      // 把 sp.points 映射到 periods 长度数组(缺失补 null, connectNulls 自动连)
      const values = new Array(periods.length).fill(null)
      for (const p of (sp.points || [])) {
        const idx = periods.findIndex(period => period.start === p.period_start)
        if (idx >= 0) values[idx] = +p.avg.toFixed(2)
      }
      series.push({
        name: `${s.normalized_breed} / ${sp.spec}`,
        type: 'line',
        data: values,
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { width: 1.6, color: COLOR_POOL[colorIdx % COLOR_POOL.length] },
        itemStyle: { color: COLOR_POOL[colorIdx % COLOR_POOL.length] },
        emphasis: { focus: 'series' },
        connectNulls: true,
      })
      colorIdx++
    }
  }
  trendChartInstance.setOption({
    grid: { left: 60, right: 20, top: 30, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: v => v != null ? `¥${v.toFixed(2)}` : '—',
    },
    legend: { type: 'scroll', top: 0, textStyle: { fontSize: 10 } },
    xAxis: {
      type: 'category',
      data: periodLabels,
      boundaryGap: false,
      axisLabel: { fontSize: 11, color: '#475569' },
    },
    yAxis: {
      type: 'value',
      axisLabel: { fontSize: 11, color: '#475569', formatter: v => '¥' + v.toFixed(0) },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    series,
  }, true)
}

// ── 阅读进度 + KPI 动画 ──────────────────────────────────────────────────
const readProgress = ref(0)
const kpiRef = ref(null)
const kpiAnimated = ref(false)
let _kpiObserver = null

function _onScrollForProgress() {
  const h = document.documentElement
  const max = h.scrollHeight - h.clientHeight
  readProgress.value = max > 0 ? Math.min(100, (window.scrollY / max) * 100) : 0
}

function _animateKpiNumber(el, target, duration = 1500) {
  let start = null
  function step(ts) {
    if (!start) start = ts
    const progress = Math.min((ts - start) / duration, 1)
    const eased = 1 - Math.pow(1 - progress, 3)
    el.textContent = Math.floor(eased * target).toLocaleString()
    if (progress < 1) requestAnimationFrame(step)
    else el.textContent = target.toLocaleString()
  }
  requestAnimationFrame(step)
}

function _setupKpiObserver() {
  if (!kpiRef.value || kpiAnimated.value) return
  _kpiObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting && !kpiAnimated.value) {
        kpiAnimated.value = true
        const els = entry.target.querySelectorAll('.kpi-number[data-target]')
        els.forEach(el => {
          const target = parseInt(el.getAttribute('data-target'))
          if (target > 0) _animateKpiNumber(el, target)
          else el.textContent = '0'
        })
        _kpiObserver.disconnect()
        _kpiObserver = null
      }
    })
  }, { threshold: 0.3 })
  _kpiObserver.observe(kpiRef.value)
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function formatKpi(n) {
  if (n == null) return '—'
  if (kpiAnimated.value) return n.toLocaleString()
  return '0'
}

watch(
  () => overview.value?.breeds_count,
  (v) => { if (v != null && v > 0) kpiAnimated.value = true },
  { immediate: true }
)

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

// ── 启动 ──────────────────────────────────────────────────
onMounted(async () => {
  await loadAll()
  await requestGeoLocation()
  await loadMarketCities()  // 2026-07-28 v3.1: 加载城市列表到 toolbar 下拉
  await loadTrendCards()  // 2026-07-28 v2: 价格走势 + 时序数据表 双卡片
  // 阅读进度 + KPI 数字动画
  window.addEventListener('scroll', _onScrollForProgress, { passive: true })
  _onScrollForProgress()
  const stopWatch = watch(
    () => [overview.value?.cities_count, overview.value?.breeds_count, overview.value?.total_records],
    (vals) => {
      if (vals.every(v => v != null && v > 0)) {
        nextTick(() => _setupKpiObserver())
        stopWatch()
      }
    },
    { immediate: true }
  )
})

onUnmounted(() => {
  window.removeEventListener('scroll', _onScrollForProgress)
  if (_kpiObserver) {
    _kpiObserver.disconnect()
    _kpiObserver = null
  }
  if (trendChartInstance) {
    trendChartInstance.dispose()
    trendChartInstance = null
  }
})
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
.m-hero {
  margin-bottom: 28px;
  padding-bottom: 20px;
  border-bottom: 1px dashed #e5e7eb;
}
.m-hero h1 {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 6px 0;
  color: #111827;
  letter-spacing: -0.5px;
}
/* 2026-07-28: hero h1 三档响应式 — 桌面 26 / 平板 22 / 手机 19 / 小屏 17 */
@media (max-width: 768px) { .m-hero h1 { font-size: 22px; } }
@media (max-width: 480px) { .m-hero h1 { font-size: 19px; } }
@media (max-width: 360px) { .m-hero h1 { font-size: 17px; } }
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

/* ── 定位状态条(2026-07-28 美化)— dropdown 永远可见,地区切换 ── */
.m-geo-bar {
  margin-top: 14px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
/* 2026-07-28: 小屏 (<480px) geo-bar 单列堆, dropdown 拉满 */
@media (max-width: 480px) {
  .m-geo-status { width: 100%; justify-content: space-between; }
  .m-geo-select { flex: 1; }
  .m-geo-reset { flex: 0 0 auto; }
}
/* 控制条 pill — 浅渐变 + 轻阴影,统一按钮视觉 */
.m-geo-status {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  background: linear-gradient(135deg, #f9fafb 0%, #f3f4f6 100%);
  color: #4b5563;
  border: 1px solid #e5e7eb;
  flex-wrap: wrap;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: border-color .2s ease, box-shadow .2s ease, background .2s ease;
}
.m-geo-icon { font-size: 14px; flex-shrink: 0; }
.m-geo-status-text {
  font-size: 12px;
  color: #6b7280;
  letter-spacing: 0.2px;
}
/* 状态变色 — 不同 GPS 状态对应不同色调(柔和渐变) */
.m-geo-status.m-geo-located {
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  color: #1e40af;
  border-color: #93c5fd;
}
.m-geo-status.m-geo-locating,
.m-geo-status.m-geo-prompting {
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  color: #92400e;
  border-color: #fcd34d;
}
.m-geo-status.m-geo-denied,
.m-geo-status.m-geo-error,
.m-geo-status.m-geo-unsupported {
  background: linear-gradient(135deg, #fef2f2 0%, #fecaca 100%);
  color: #991b1b;
  border-color: #fca5a5;
}
/* 状态后缀(本地缓存 / 手动)— 继承父色,自动调整 */
.m-geo-source {
  font-size: 11px;
  color: inherit;
  opacity: 0.7;
  font-weight: normal;
  margin-left: 2px;
}
/* 地区切换 dropdown — 自定义箭头 + polished(高度与按钮对齐 30px) */
.m-geo-select {
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  padding: 4px 30px 4px 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background-color: #fff;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' fill='none' stroke='%23475569' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3e%3cpath d='M2.5 4.5l3.5 3.5 3.5-3.5'/%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 10px center;
  background-size: 12px 12px;
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  color: #1e40af;
  cursor: pointer;
  outline: none;
  transition: border-color .15s ease, box-shadow .15s ease, background-color .15s ease;
  min-width: 90px;
  height: 30px;
}
.m-geo-select:hover {
  border-color: #93c5fd;
  background-color: #f8fafc;
}
.m-geo-select:focus,
.m-geo-select:focus-visible {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
}
.m-geo-select:disabled {
  background-color: #f3f4f6;
  color: #9ca3af;
  cursor: not-allowed;
  border-color: #e5e7eb;
  opacity: 0.7;
}
/* 重新定位/重试按钮 — 与 dropdown 同高 30px,精致 ghost button */
.m-geo-reset {
  margin-left: 2px;
  padding: 0 12px;
  height: 30px;
  background: #fff;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  color: #6b7280;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.m-geo-reset:hover {
  background: #f9fafb;
  border-color: #93c5fd;
  color: #1e40af;
  box-shadow: 0 1px 2px rgba(59, 130, 246, 0.08);
}
.m-geo-reset:active {
  transform: translateY(1px);
}

/* ── KPI ── */
.m-kpi {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}
@media (max-width: 768px) {
  .m-kpi { grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .m-kpi-item { padding: 12px 12px; }
  .m-kpi-value { font-size: 20px; }
  .m-kpi-label, .m-kpi-sub { font-size: 11px; }
}
.m-kpi-item {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 14px 16px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.m-kpi-item:hover {
  border-color: #d1d5db;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.m-kpi-label {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 6px;
  font-weight: 500;
}
.m-kpi-value {
  font-size: 22px;
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

/* ── 价格走势 + 时序数据表 双卡片(2026-07-28 v2 — /market 嵌 /trend 简化版) ── */
.m-card-head {
  margin-bottom: 16px;
  display: flex; align-items: flex-start; justify-content: space-between;
  flex-wrap: wrap; gap: 12px;
}
.m-trend-chart-card,
.m-trend-table-card { /* 复用 .m-card 通用样式 */ }
.m-trend-chart-title {
  font-size: 18px; font-weight: 700; color: #111827;
  margin: 0; letter-spacing: -0.2px;
}
.m-trend-chart-sub {
  font-size: 13px; color: #6b7280;
  margin: 0; line-height: 1.5;
}
/* 2026-07-28 v3.1: toolbar — 城市/期数 select + 品种搜索 input + 重选按钮 */
.m-trend-toolbar {
  display: flex; align-items: center; gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.m-trend-select {
  height: 32px;
  padding: 0 28px 0 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background-color: #fff;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' fill='none' stroke='%23475569' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3e%3cpath d='M2.5 4.5l3.5 3.5 3.5-3.5'/%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 8px center;
  background-size: 12px 12px;
  font-size: 13px;
  font-family: inherit;
  color: #1e40af;
  font-weight: 500;
  cursor: pointer;
  outline: none;
  transition: border-color .15s, box-shadow .15s;
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  min-width: 90px;
}
.m-trend-select:hover { border-color: #93c5fd; }
.m-trend-select:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}
.m-trend-select:disabled {
  background-color: #f3f4f6; color: #9ca3af; cursor: wait;
}
.m-trend-search-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
}
.m-trend-search-input {
  height: 32px;
  padding: 0 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 13px;
  background: #fff;
  min-width: 220px;
  outline: none;
  transition: border-color .15s, box-shadow .15s;
  color: #111827;
  font-family: inherit;
}
.m-trend-search-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}
/* v3.3: 输入框右侧 × 清空按钮 */
.m-trend-search-clear {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 22px; height: 22px;
  display: inline-flex; align-items: center; justify-content: center;
  background: #f3f4f6;
  color: #6b7280;
  border: none; border-radius: 50%;
  font-size: 16px; line-height: 1;
  cursor: pointer;
  padding: 0;
  transition: background .12s, color .12s;
}
.m-trend-search-clear:hover {
  background: #e5e7eb;
  color: #111827;
}
/* v3.3: 搜索错误提示 */
.m-trend-search-error {
  flex-basis: 100%;
  font-size: 12px;
  color: #dc2626;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 6px 10px;
  margin-top: 4px;
  width: 100%;
}
.m-trend-refresh-btn {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 0 12px;
  height: 32px;
  background: linear-gradient(135deg, #3b82f6 0%, #1e40af 100%);
  color: #fff;
  border: none; border-radius: 6px;
  font-size: 12px; font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(30, 64, 175, 0.2);
  transition: transform .15s ease, box-shadow .15s ease;
  white-space: nowrap;
}
.m-trend-refresh-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(30, 64, 175, 0.3);
}
.m-trend-refresh-btn:active { transform: translateY(0); }
@media (max-width: 640px) {
  .m-trend-toolbar { width: 100%; }
  .m-trend-search-input { min-width: 0; flex: 1; }
  .m-trend-select { min-width: 0; flex: 1; }
}
.m-trend-chart-info { flex: 1; min-width: 0; }
.m-trend-chart {
  width: 100%; height: 380px;
}
.m-trend-status {
  text-align: center; color: #9ca3af;
  background: #fafbfc; border: 1px dashed #e5e7eb; border-radius: 8px;
  padding: 40px 20px; font-size: 13px;
  margin-top: 12px;
}

/* 时序数据表 */
.m-trend-table-scroll {
  width: 100%;
  overflow-x: auto;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}
.m-trend-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  font-feature-settings: "tnum";
  white-space: nowrap;
}
.m-trend-table thead {
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  border-bottom: 1px solid #e5e7eb;
}
.m-trend-table th {
  padding: 10px 12px;
  font-weight: 600;
  color: #475569;
  text-align: left;
  font-size: 12px;
  letter-spacing: 0.2px;
  border-right: 1px solid #f1f5f9;
  position: sticky; top: 0;
  background: #f8fafc;
}
.m-trend-table th:last-child { border-right: none; }
.m-trend-th-trend { color: #1e40af !important; }
.m-trend-table tbody tr {
  border-bottom: 1px solid #f1f5f9;
  transition: background .12s;
}
.m-trend-table tbody tr:hover { background: #f8fafc; }
.m-trend-table tbody tr:last-child { border-bottom: none; }
.m-trend-cell-material {
  font-weight: 600; color: #111827;
  padding: 10px 12px;
  border-right: 1px solid #f1f5f9;
  position: sticky; left: 0;
  background: inherit;
}
.m-trend-cell-spec {
  padding: 10px 12px;
  color: #1e40af;
  font-weight: 500;
  border-right: 1px solid #f1f5f9;
  max-width: 160px;
  overflow: hidden; text-overflow: ellipsis;
}
.m-trend-cell-unit {
  padding: 10px 12px;
  color: #6b7280;
  font-size: 12px;
  border-right: 1px solid #f1f5f9;
}
.m-trend-cell-price {
  padding: 8px 12px;
  text-align: right;
  border-right: 1px solid #f1f5f9;
  min-width: 78px;
}
.m-trend-price-val {
  color: #111827;
  font-weight: 600;
  font-size: 13px;
  line-height: 1.3;
}
.m-trend-price-meta {
  color: #9ca3af;
  font-size: 10px;
  margin-top: 1px;
  letter-spacing: 0.2px;
}
.m-trend-cell-trend {
  padding: 8px 12px;
  text-align: right;
  border-right: 1px solid #f1f5f9;
  min-width: 88px;
  background: #fafbfc;
}
.m-trend-pct {
  font-weight: 700;
  font-size: 13px;
  line-height: 1.3;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.m-trend-up { color: #dc2626; }
.m-trend-down { color: #16a34a; }
.m-trend-flat { color: #6b7280; }
.m-trend-strong { font-weight: 700; }
.m-trend-mild { font-weight: 600; }
.m-trend-abs {
  font-size: 11px;
  color: #6b7280;
  margin-top: 1px;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.m-trend-no-data {
  color: #d1d5db;
  font-size: 12px;
}
@media (max-width: 640px) {
  .m-trend-chart { height: 280px; }
  .m-trend-table { font-size: 12px; }
  .m-trend-cell-price, .m-trend-cell-trend { min-width: 64px; padding: 6px 8px; }
}

/* ── 数据来源 + 新鲜度 合并卡(2026-07-28)— 替代原两张卡 ── */
.m-card-quality { /* 复用 .m-card */ }
.m-quality-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 14px; flex-wrap: wrap; gap: 8px;
}
.m-quality-toolbar-info { flex: 1; min-width: 0; }
.m-quality-title { font-size: 18px; font-weight: 700; margin: 0 0 4px 0; color: #111827; }
.m-quality-toolbar-sub { font-size: 13px; color: #6b7280; margin: 0; line-height: 1.5; }
.m-quality-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.m-quality-card {
  display: flex; flex-direction: row; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 8px;
  background: #f9fafb; border: 1px solid #e5e7eb;
  font-size: 12px;
  text-decoration: none;
  color: inherit;
  transition: border-color .15s, background .15s, box-shadow .15s;
}
.m-quality-link:hover {
  border-color: #3b82f6;
  background: #eff6ff;
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.1);
}
.m-quality-nolink { cursor: default; }
.m-quality-emoji {
  font-size: 16px;
  flex-shrink: 0;
  width: 20px;
  text-align: center;
}
.m-quality-info {
  display: flex; flex-direction: column; flex: 1; min-width: 0; gap: 2px;
}
.m-quality-row1 {
  display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap;
}
.m-quality-row2 {
  display: flex; align-items: baseline; gap: 4px;
  font-size: 11px; color: #6b7280;
}
.m-quality-label {
  font-weight: 600; color: #111827; font-size: 13px;
}
.m-quality-province {
  font-size: 10px; color: #6b7280;
  padding: 1px 6px; background: #f3f4f6;
  border-radius: 4px;
}
.m-quality-arrow {
  font-size: 13px; color: #6b7280;
  margin-left: auto; flex-shrink: 0;
}
.m-quality-link:hover .m-quality-arrow { color: #3b82f6; }
.m-quality-age {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-weight: 600;
}
.m-quality-date { color: #9ca3af; }
.m-quality-docs { color: #9ca3af; }
.m-quality-sep { color: #d1d5db; }
.m-quality-ok .m-quality-emoji { color: #16a34a; }
.m-quality-warn .m-quality-emoji { color: #d97706; }
.m-quality-alert .m-quality-emoji { color: #dc2626; }

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

/* ── 回到顶部 ── */
.m-back-to-top-wrap {
  display: flex; justify-content: center; margin: 20px 0;
}
.m-back-to-top {
  padding: 8px 18px;
  background: #fff;
  border: 1px solid #d1d5db;
  border-radius: 999px;
  font-size: 12px;
  font-family: inherit;
  color: #6b7280;
  cursor: pointer;
  transition: all .15s;
}
.m-back-to-top:hover {
  background: #f9fafb;
  border-color: #9ca3af;
  color: #111827;
}

/* ── 阅读进度条 ── */
.read-progress {
  position: fixed;
  top: 0; left: 0;
  height: 3px;
  background: linear-gradient(90deg, #3b82f6 0%, #1e40af 100%);
  z-index: 100;
  transition: width .1s ease-out;
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
.m-footnote-warn {
  color: #b45309;
  background: #fef3c7;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}
</style>