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

      <!-- 2026-07-28 v1.0: 半年价格趋势卡(单图 10 品种 × 6 月均价)— 替代原热力图 -->
      <section v-if="provinceTrend.breeds?.length || trendLoading" class="m-card m-card-trend">
        <header class="m-trend-toolbar">
          <div class="m-trend-toolbar-info">
            <h2 class="m-trend-title">📈 {{ userProvince || '全国' }} · 半年价格趋势</h2>
            <p class="m-trend-toolbar-sub">
              近 {{ provinceTrend.periods?.length || 6 }} 期(月度) ·
              {{ provinceTrend.breeds?.length || 0 }} 个品种 ·
              每条线 = 该品种在{{ userProvince || '全国' }}所有城市的均价
            </p>
          </div>
          <div class="m-trend-toolbar-actions">
            <!-- 2026-07-28: 搜索品种加进图表(用户选定的品种 sticky,直到"🎲 换一组") -->
            <div class="m-trend-search-wrap">
              <input
                v-model="breedSearch"
                type="text"
                class="m-trend-search-input"
                placeholder="🔍 搜索品种加进图…"
                @input="onBreedSearchInput"
                @keydown.enter="onBreedSearchEnter"
                @focus="breedSearchOpen = breedSearchResults.length > 0"
              />
              <div
                v-if="breedSearchOpen && breedSearchResults.length > 0"
                class="m-trend-search-dropdown"
                @mousedown.prevent
              >
                <button
                  v-for="r in breedSearchResults"
                  :key="r.breed"
                  type="button"
                  class="m-trend-search-result"
                  :class="{ selected: selectedBreeds.includes(r.breed) }"
                  :disabled="selectedBreeds.includes(r.breed)"
                  @mousedown.prevent="addBreedFromSearch(r)"
                >
                  <span class="m-trend-search-name">{{ r.breed }}</span>
                  <span v-if="r.category_name_l3" class="m-trend-search-l3">{{ r.category_name_l3 }}</span>
                  <span class="m-trend-search-docs">{{ r.records || 0 }}</span>
                  <span v-if="selectedBreeds.includes(r.breed)" class="m-trend-search-tag">已加</span>
                </button>
              </div>
              <div v-if="breedSearchLoading" class="m-trend-search-loading">搜索中…</div>
            </div>
            <button
              class="m-trend-refresh-btn"
              type="button"
              :disabled="refreshingBreeds"
              @click="refreshRandomBreeds"
              title="随机换一组(清空用户选择)"
            >
              <span class="m-trend-refresh-icon" :class="{ spinning: refreshingBreeds }">🎲</span>
              换一组品种
            </button>
          </div>
        </header>
        <div ref="trendChartRef" class="m-trend-chart"></div>
        <div v-if="trendLoading && !provinceTrend.breeds?.length" class="m-trend-loading">加载中…</div>
        <div v-if="!provinceTrend.breeds?.length && !trendLoading" class="m-trend-empty">
          {{ userProvince ? `${userProvince} 暂无历史价数据` : '全国暂无历史价数据' }}
          (月度聚合 ≥ 1 条才出图)
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
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useHead } from '@unhead/vue'
import { useEcharts } from '../composables/useEcharts'
import { registerGovPriceTheme, GOV_PRICE_PALETTE } from '../composables/useEchartsTheme'

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
        name: 'ChinaJT · 工程造价材料价格数据 · 17 城住建局官方期刊',
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

// 半年价格趋势
const provinceTrend = ref({ province: '', periods: [], breeds: [] })
const trendChartRef = ref(null)
const trendChart = ref(null)
const trendLoading = ref(false)
const refreshingBreeds = ref(false)
// 2026-07-28: 用户搜的品种(sticky,直到"🎲 换一组"或省份切换)
const selectedBreeds = ref([])
// 搜索框状态
const breedSearch = ref('')
const breedSearchResults = ref([])
const breedSearchLoading = ref(false)
const breedSearchOpen = ref(false)
let breedSearchTimer = null

// 文档点击关闭 dropdown(搜索框内点击不算)
function _onDocMousedown(e) {
  const wrap = document.querySelector('.m-trend-search-wrap')
  if (wrap && wrap.contains(e.target)) return
  breedSearchOpen.value = false
}
const registerGovPriceThemeOnce = (() => {
  let done = false
  return async () => { if (!done) { await registerGovPriceTheme(); done = true; } }
})()

const loading = ref(true)
const loadError = ref('')

// ── fetch helper ──────────────────────────────────────────────────
async function fetchJson(path) {
  // 公开页守卫: /market 只能调 /api/market/*
  if (!path.startsWith('/api/market/')) {
    throw new Error(`[market-view-guard] /market 页面禁止调用 ${path}\n允许范围: /api/market/*`)
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

// ── 半年价格趋势(10 品种 × 6 月均价,单图多线) ──────────────────────────────────────────────────
// 2026-07-28: 搜索品种(300ms debounce → /api/market/breed-search)
function onBreedSearchInput() {
  const q = breedSearch.value.trim()
  if (breedSearchTimer) clearTimeout(breedSearchTimer)
  if (!q) {
    breedSearchResults.value = []
    breedSearchOpen.value = false
    return
  }
  breedSearchTimer = setTimeout(() => searchBreeds(q), 300)
}

async function searchBreeds(q) {
  breedSearchLoading.value = true
  try {
    // 2026-07-28: 带当前定位省份,搜索只在该省数据池里挑(避免搜出异地品种)
    const params = new URLSearchParams()
    params.set('q', q)
    params.set('limit', '15')
    if (userProvince.value) params.set('province', userProvince.value)
    const data = await fetchJson(`/api/market/breed-search?${params.toString()}`)
    // 客户端排序:exact > prefix > contains > 其他(ES wildcard 不算 relevance)
    const qLower = q.toLowerCase()
    const scored = (data.results || []).map(r => {
      const name = r.breed.toLowerCase()
      let score = 3
      if (name === qLower) score = 0
      else if (name.startsWith(qLower)) score = 1
      else if (name.includes(qLower)) score = 2
      return { r, score }
    })
    scored.sort((a, b) => a.score - b.score || (b.r.records || 0) - (a.r.records || 0))
    breedSearchResults.value = scored.map(s => s.r)
    breedSearchOpen.value = breedSearchResults.value.length > 0
  } catch (e) {
    console.error('[breed-search]', e)
    breedSearchResults.value = []
  } finally {
    breedSearchLoading.value = false
  }
}

function addBreedFromSearch(r) {
  if (selectedBreeds.value.includes(r.breed)) {
    // 已加,仅清空输入框
    breedSearch.value = ''
    breedSearchResults.value = []
    breedSearchOpen.value = false
    return
  }
  selectedBreeds.value = [...selectedBreeds.value, r.breed]
  breedSearch.value = ''
  breedSearchResults.value = []
  breedSearchOpen.value = false
  loadProvinceTrend()
}

function onBreedSearchEnter() {
  if (breedSearchTimer) {
    clearTimeout(breedSearchTimer)
    breedSearchTimer = null
  }
  const q = breedSearch.value.trim()
  if (!q) return
  if (breedSearchResults.value.length > 0) {
    addBreedFromSearch(breedSearchResults.value[0])
    return
  }
  searchBreeds(q).then(() => {
    if (breedSearchResults.value.length > 0) {
      addBreedFromSearch(breedSearchResults.value[0])
    }
  })
}

async function loadProvinceTrend() {
  trendLoading.value = true
  try {
    const params = new URLSearchParams()
    if (userProvince.value) params.set('province', userProvince.value)
    params.set('months', '6')
    if (selectedBreeds.value.length > 0) {
      // 用户已选品种 → 后端按用户顺序返回(不随机)
      params.set('breeds', selectedBreeds.value.join(','))
    } else {
      params.set('limit', '10')
    }
    const r = await fetchJson(`/api/market/province-trend?${params.toString()}`)
    provinceTrend.value = r
    // 同步 selectedBreeds — 后端可能过滤了无数据的品种
    if (r.breeds?.length) {
      selectedBreeds.value = r.breeds.map(b => b.breed)
    }
    await nextTick()
    renderTrendChart()
  } catch (e) {
    console.error('[market] province-trend 失败', e)
    provinceTrend.value = { province: userProvince.value || '', periods: [], breeds: [] }
  } finally {
    trendLoading.value = false
  }
}

async function refreshRandomBreeds() {
  if (refreshingBreeds.value) return
  refreshingBreeds.value = true
  try {
    selectedBreeds.value = []  // 清空用户选择 → 走 random 10
    await loadProvinceTrend()
  } finally {
    refreshingBreeds.value = false
  }
}

async function renderTrendChart() {
  if (!trendChartRef.value) return
  await registerGovPriceThemeOnce()
  if (!trendChart.value) {
    const echarts = await useEcharts()
    trendChart.value = echarts.init(trendChartRef.value, 'govPrice')
  }
  const data = provinceTrend.value
  if (!data || !data.periods?.length || !data.breeds?.length) {
    trendChart.value.clear()
    return
  }
  const periodLabels = data.periods.map(p => p.label)
  const numPeriods = periodLabels.length
  const series = data.breeds.map((b, i) => {
    // 把 points 映射到 numPeriods 长度数组(缺失补 null, connectNulls 自动连)
    const values = new Array(numPeriods).fill(null)
    for (const p of b.points) {
      if (p.period_idx >= 0 && p.period_idx < numPeriods) {
        values[p.period_idx] = +p.avg_price.toFixed(2)
      }
    }
    return {
      name: b.breed,
      type: 'line',
      data: values,
      smooth: true,
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 1.8, color: GOV_PRICE_PALETTE[i % GOV_PRICE_PALETTE.length] },
      itemStyle: { color: GOV_PRICE_PALETTE[i % GOV_PRICE_PALETTE.length] },
      emphasis: { focus: 'series' },
      connectNulls: true,
    }
  })

  trendChart.value.setOption({
    grid: { left: 60, right: 20, top: 50, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: v => v != null ? `¥${v.toFixed(2)}` : '—',
    },
    legend: { type: 'scroll', top: 5, textStyle: { fontSize: 11 } },
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

// userProvince 变化 → 重拉趋势(初次 mounted 不触发,因为 watch 立即触发一次)
//   实际上 watch 默认 lazy,只有 userProvince 从非空变非空、或初次赋值才触发
//   我们在 onMounted 里手动调一次 loadProvinceTrend,所以这里 watch 用来响应后续变化
watch(userProvince, (newP, oldP) => {
  if (newP !== oldP) {
    selectedBreeds.value = []  // 2026-07-28: 切省份时清空,避免旧品种在新省份没数据
    loadProvinceTrend()
  }
})

onUnmounted(() => {
  if (trendChart.value) trendChart.value.dispose()
  document.removeEventListener('mousedown', _onDocMousedown)
})

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
  await loadProvinceTrend()  // 首次加载,后续 watch 触发
  // 2026-07-28: 文档点击关闭品种搜索 dropdown
  document.addEventListener('mousedown', _onDocMousedown)
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

/* ── 定位状态条(2026-07-28) ── */
.m-geo-bar {
  margin-top: 14px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.m-geo-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  background: #f3f4f6;
  color: #4b5563;
  border: 1px solid #e5e7eb;
  flex-wrap: wrap;
}
.m-geo-icon { font-size: 14px; }
.m-geo-status.m-geo-located {
  background: #eff6ff;
  color: #1e40af;
  border-color: #bfdbfe;
}
.m-geo-status.m-geo-locating,
.m-geo-status.m-geo-prompting {
  background: #fef3c7;
  color: #92400e;
  border-color: #fde68a;
}
.m-geo-status.m-geo-denied,
.m-geo-status.m-geo-error,
.m-geo-status.m-geo-unsupported {
  background: #fef2f2;
  color: #991b1b;
  border-color: #fecaca;
}
.m-geo-province {
  font-weight: 700;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.m-geo-source {
  font-size: 11px;
  color: #6b7280;
  font-weight: normal;
}
.m-geo-select {
  margin-left: 4px;
  padding: 3px 8px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #fff;
  font-size: 13px;
  font-family: inherit;
  color: #111827;
  cursor: pointer;
  outline: none;
}
.m-geo-select:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}
.m-geo-reset {
  margin-left: 4px;
  padding: 3px 10px;
  background: #fff;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 12px;
  font-family: inherit;
  color: #6b7280;
  cursor: pointer;
  transition: all 0.15s;
}
.m-geo-reset:hover {
  background: #f9fafb;
  border-color: #9ca3af;
  color: #111827;
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

/* ── 趋势卡(2026-07-28 v1.0:替代原热力图) ── */
.m-card-trend { /* 复用 .m-card 通用样式 */ }
.m-trend-toolbar {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 16px; margin-bottom: 18px; flex-wrap: wrap;
}
.m-trend-toolbar-info { flex: 1; min-width: 0; }
.m-trend-title {
  color: #111827; letter-spacing: -.3px; margin: 0 0 4px;
  font-size: 18px; font-weight: 700;
}
.m-trend-toolbar-sub {
  color: #6b7280; margin: 0; font-size: 13px; line-height: 1.5;
}
.m-trend-toolbar-actions {
  display: flex; align-items: center; gap: 10px; flex-shrink: 0;
}
/* 2026-07-28: 搜索品种 dropdown — 加选品种进图表 */
.m-trend-search-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
}
.m-trend-search-input {
  height: 36px;
  padding: 0 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 13px;
  background: #fff;
  min-width: 200px;
  outline: none;
  transition: border-color .15s, box-shadow .15s;
  color: #111827;
  font-family: inherit;
}
.m-trend-search-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}
.m-trend-search-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 0; right: 0;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-top: 3px solid #3b82f6;
  border-radius: 10px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.12), 0 2px 8px rgba(15, 23, 42, 0.06);
  max-height: 320px;
  overflow-y: auto;
  z-index: 50;
  min-width: 280px;
}
.m-trend-search-result {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 12px;
  text-align: left;
  background: none;
  border: none;
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
  color: #111827;
  transition: background .12s;
}
.m-trend-search-result:hover:not(:disabled) {
  background: #f0f9ff;
}
.m-trend-search-result:disabled,
.m-trend-search-result.selected {
  background: #dbeafe;
  color: #1d4ed8;
  cursor: default;
}
.m-trend-search-name {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.m-trend-search-l3 {
  font-size: 11px;
  color: #6b7280;
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.m-trend-search-docs {
  font-size: 11px;
  color: #9ca3af;
  font-family: ui-monospace, monospace;
  flex-shrink: 0;
}
.m-trend-search-tag {
  font-size: 10px;
  color: #1e40af;
  background: #bfdbfe;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.m-trend-search-loading {
  position: absolute;
  top: 50%; right: 10px;
  transform: translateY(-50%);
  font-size: 11px;
  color: #6b7280;
  background: rgba(255,255,255,0.9);
  padding: 0 4px;
  pointer-events: none;
}
/* 换一组品种按钮(主操作色,显眼) */
.m-trend-refresh-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px;
  background: linear-gradient(135deg, #3b82f6 0%, #1e40af 100%);
  color: #fff;
  border: none; border-radius: 8px;
  font-size: 13px; font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(30, 64, 175, 0.2);
  transition: transform .15s ease, box-shadow .15s ease;
  white-space: nowrap;
}
.m-trend-refresh-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(30, 64, 175, 0.3);
}
.m-trend-refresh-btn:disabled {
  opacity: .7; cursor: not-allowed; box-shadow: none;
}
.m-trend-refresh-icon {
  font-size: 14px; display: inline-block; line-height: 1;
}
.m-trend-refresh-icon.spinning {
  animation: m-refresh-spin .8s linear infinite;
}
@keyframes m-refresh-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
.m-trend-chart {
  width: 100%; height: 360px;
}
.m-trend-loading {
  text-align: center; color: #6b7280;
  padding: 20px; font-size: 13px;
}
.m-trend-empty {
  text-align: center; color: #9ca3af;
  background: #fafbfc; border: 1px dashed #e5e7eb; border-radius: 8px;
  padding: 40px 20px; font-size: 13px;
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