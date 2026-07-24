<!--
  MarketView.vue (2026-07-21)
  /market 公开市场行情页 — 不鉴权,访客可直访
  品类 × 城市 热力图 + 跨城归一价格聚合
  数据源: /api/market/* (公开)
-->
<template>
  <div class="market">
    <!-- 阅读进度条(2026-07-24 复用 /home 风格,主品牌色) -->
    <div class="read-progress" :style="{ width: readProgress + '%' }"></div>

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
        <!-- 2026-07-24 Hero CTA(锚点跳热力图 + 数据来源) -->
        <div class="m-hero-ctas">
          <a href="#heatmap" class="cta-button" @click.prevent="scrollTo('heatmap')">🌡️ 看热力图 ↓</a>
          <a href="#source" class="cta-button cta-secondary" @click.prevent="scrollTo('source')">数据来源 →</a>
        </div>
      </section>

      <!-- 01 OVERVIEW -->
      <div class="section-marker">
        <span class="section-num">01</span>
        <span class="section-divider"></span>
        <span class="section-tagline">OVERVIEW</span>
      </div>

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

      <!-- 02 HEATMAP -->
      <div class="section-marker" id="heatmap">
        <span class="section-num">02</span>
        <span class="section-divider"></span>
        <span class="section-tagline">HEATMAP</span>
      </div>

      <!-- 热力图 -->

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

        <!-- 2026-07-24 删除: 搜索 / 默认推荐卡片 — 默认 12 品种 loadRandomBreeds 完成直接喂给热力图,
             下方属性筛选面板 (m-selection-panel) 仍保留用于精筛。-->

        <!-- v0.24: 属性筛选 — 强制单选(每 k 选一个 v,跨 k 是 AND 关系) -->
        <!-- v0.29: 改 checkbox 多选 toggle + 顶部"应用"按钮(避免每点 reload) + chips + reset 合一进折叠面板 -->
        <aside v-if="selectedBreeds.length || attrFilterTotal" class="m-selection-panel" :class="{ expanded: attrExpanded }">
          <header class="m-selection-panel-header">
            <!-- 2026-07-24: header 改为纯标签(不可点)。点击展开换成下面 body 里的"展开属性筛选"按钮 — 更直观 -->
            <span class="m-selection-panel-title">
              <span class="m-panel-icon">🔎</span>
              <span class="m-panel-title-text">已应用筛选</span>
            </span>
            <div class="m-selection-panel-actions">
              <button class="m-link-btn m-link-btn-danger" type="button" title="清空所有品种 + 属性筛选" @click="resetSelection">↻ 重置</button>
            </div>
          </header>
          <div class="m-selection-panel-body">
            <!-- v0.35: 已应用筛选摘要行(pill 从 header 移到 body 顶部,多筛选时不再挤兑 chevron) -->
            <div class="m-selection-summary">
              <span class="m-pill m-pill-blue">{{ selectedBreeds.length }} 品种</span>
              <span v-if="attrFilterTotal" class="m-pill m-pill-blue">{{ attrFilterTotal }} 属性</span>
              <span v-if="attrDirty" class="m-pill m-pill-warn">● 未应用</span>
              <span v-else-if="(selectedBreeds.length || attrFilterTotal)" class="m-pill m-pill-good">✓ 同步</span>
            </div>
            <!-- 已选品种 chips — 2026-07-24: 品种部分默认展示,只靠 × 逐个删 -->
            <div v-if="selectedBreeds.length" class="m-selected-chips-row">
              <div class="m-selected-chips-list">
                <div
                  v-for="b in selectedBreeds"
                  :key="b"
                  class="m-selected-chip"
                >
                  <span class="m-selected-chip-icon">✅</span>
                  <span class="m-selected-chip-text">{{ b }}</span>
                  <button class="m-selected-chip-clear" title="移除该品种" @click="removeBreed(b)">×</button>
                </div>
                <!-- 2026-07-24 删除: 清空品种按钮(原 m-selected-chips-clear-all)— 清品种全靠 × 逐个删 -->
              </div>
            </div>

            <!-- 2026-07-24: 收起状态 → 显示一个直观的"展开属性筛选"按钮 -->
            <button
              v-if="attrKeys.length && !attrExpanded"
              type="button"
              class="m-attr-expand-btn"
              @click="attrExpanded = true"
            >
              <span class="m-attr-expand-icon">▼</span>
              <span>展开属性筛选</span>
              <span v-if="attrFilterTotal" class="m-attr-expand-count">(已勾 {{ attrFilterTotal }})</span>
            </button>

            <!-- 属性筛选 — 2026-07-24: 默认收起,点上面按钮展开 -->
            <div v-if="attrKeys.length && attrExpanded" class="m-attr-filters">
              <div class="m-attr-header">
                <span class="m-attr-header-label">
                  属性筛选(可多选 · 不点应用不刷热力图)
                  <span v-if="attrFilterTotal" class="m-attr-header-count">{{ attrFilterTotal }} 已勾</span>
                </span>
                <button class="m-link-btn" type="button" @click="attrExpanded = false">▲ 收起</button>
                <button class="m-spec-link" @click="clearAttrFilters">清空属性</button>
              </div>
              <div v-for="k in attrKeys" :key="k.key" class="m-attr-row">
                <span class="m-attr-key-label" :title="k.key">{{ k.label || k.key }}</span>
                <div class="m-attr-values">
                  <label
                    v-for="v in k.values"
                    :key="v.value"
                    class="m-attr-check"
                    :class="{ active: isAttrSelected(k.key, v.value) }"
                    :title="`${k.key}=${v.value} · ${v.docs} 条`"
                  >
                    <input
                      type="checkbox"
                      :checked="isAttrSelected(k.key, v.value)"
                      @change="toggleAttrValue(k.key, v.value)"
                    />
                    <span class="m-attr-check-text">{{ v.value }}</span>
                    <span class="m-attr-check-count">{{ v.docs }}</span>
                  </label>
                </div>
              </div>
              <div class="m-apply-row">
                <button
                  class="m-apply-btn"
                  :class="{ ready: attrDirty }"
                  :disabled="!attrDirty"
                  type="button"
                  @click="applyAttrFilters"
                  :title="attrDirty ? '应用属性筛选并刷新热力图' : '没有未应用的改动'"
                >
                  <span class="m-apply-btn-icon">{{ attrDirty ? '🚀' : '✓' }}</span>
                  {{ attrDirty ? '应用属性筛选' : '已是最新' }}
                </button>
                <span v-if="attrDirty" class="m-apply-hint">
                  {{ attrFilterTotal }} 项已勾选 · 点上方按钮刷新热力图
                </span>
                <span v-else-if="attrFilterTotal" class="m-apply-hint">
                  {{ attrFilterTotal }} 项已生效 · 再勾触发"未应用"状态
                </span>
              </div>
            </div>
          </div>
        </aside>

        <!-- 2026-07-24 删除: 横向扩展 12 个品种面板(m-extend-breeds-panel) — 简化 UX,默认直接看热力图 -->

        <div v-if="loading && !heatmap.breeds.length" class="m-empty">
          ⏳ 正在加载默认 12 个品种的热力图…
        </div>
        <div
          v-else-if="heatmap.breeds.length && heatmap.cities.length"
          class="m-heatmap-chunks"
        >
          <div
            v-for="chunk in heatmapChunks"
            :key="chunk.key"
            class="m-heatmap-block"
          >
            <div v-if="chunk.title" class="m-heatmap-chunk-title">{{ chunk.title }}</div>
            <div class="m-heatmap-scroll">
              <div
                class="m-heatmap-grid"
                :style="chunkGridStyle(chunk.cities.length)"
              >
                <!-- 表头 -->
                <div class="m-heatmap-cell m-heatmap-corner">品种 \ 城市</div>
                <div
                  v-for="city in chunk.cities"
                  :key="'h' + city.key"
                  class="m-heatmap-cell m-heatmap-th"
                >
                  {{ city.label }}
                </div>
                <!-- 数据行 -->
                <template v-for="(breed, bi) in heatmap.breeds" :key="chunk.key + '-' + breed.breed + (breed.spec_fingerprint || '')">
                  <div class="m-heatmap-cell m-heatmap-row-label">
                    <div class="m-row-name">{{ breed.breed }}</div>
                    <!-- v0.31 重构: 多源 fallback + 主+副结构,永不显示 — -->
                    <div class="m-row-meta">
                      <!-- 主标: spec_label > category_name_l3 > category_name_l1 > breed -->
                      <span class="m-meta-pri" :class="{ 'm-meta-fallback': !breed.spec_label && !breed.category_name_l3 && !breed.category_name_l1 }">
                        <template v-if="breed.spec_label">{{ breed.spec_label }}</template>
                        <template v-else-if="breed.category_name_l3">{{ breed.category_name_l3 }}</template>
                        <template v-else-if="breed.category_name_l1">{{ breed.category_name_l1 }}</template>
                        <template v-else>全规格聚合</template>
                      </span>
                      <!-- 副标: 有 unit/records 时显示 -->
                      <span v-if="breed.unit || breed.records > 0" class="m-meta-sub">
                        <template v-if="breed.unit">· {{ breed.unit }}</template>
                        <template v-if="breed.records > 0">· {{ breed.records }} 城有数据</template>
                      </span>
                    </div>
                  </div>
                  <div
                    v-for="(city, ci) in chunk.cities"
                    :key="chunk.key + '-' + breed.breed + '-' + city.key"
                    class="m-heatmap-cell"
                    :style="cellStyle(chunk.matrix[bi]?.[ci])"
                    :title="cellTitle(breed, city, chunk.matrix[bi]?.[ci])"
                  >
                    {{ formatCell(chunk.matrix[bi]?.[ci]) }}
                  </div>
                </template>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="m-empty">该品种暂无热力图数据</div>
      </section>

      <!-- 04 SOURCE -->
      <div class="section-marker" id="source">
        <span class="section-num">04</span>
        <span class="section-divider"></span>
        <span class="section-tagline">SOURCE</span>
      </div>

      <!-- 2026-07-24 回到顶部(配合 read-progress 暗示) -->
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
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import SectionHeader from './SectionHeader.vue'

// 2026-07-23: /market 只接 v=timestamp URL 参数(作 cache buster 拼到 API 请求后)
// 其他参数 (date_from/date_to 等) 均忽略
const route = useRoute()
const cacheVersion = computed(() => {
  const v = route.query.v
  return v && String(v).trim() ? String(v).trim() : ''
})

function withCacheBuster(path) {
  if (!cacheVersion.value) return path
  // 如果路径已有 query,追加 &v=,否则加 ?v=
  return path.includes('?') ? `${path}&v=${cacheVersion.value}` : `${path}?v=${cacheVersion.value}`
}

const overview = ref({})
const heatmap = ref({ breeds: [], cities: [], matrix: [], spec_fingerprint: null })

// 热力图选择器状态(v0.28: 多选 — selectedBreeds 数组支持勾多个品种)
const selectedBreeds = ref([])        // 已选品种名数组
// 2026-07-24 删除: breedSearch / searchResults / searchLoading / randomBreeds / recommendBreeds / extendBreeds
//   页面无搜索 UI,loadRandomBreeds 直接喂给 selectedBreeds 跳热力图
const attrKeys = ref([])              // [{key, label, values: [{value, docs}], total_docs}, ...]  v0.2 (2026-07-22) 加 label
const attrFilters = ref({})          // {key: [values]} — 各 k 独立多选
const loadingAttrKeys = ref(false)

// v0.29: 折叠面板 + 应用前/后分离 — 避免 checkbox toggle 每次 reload
//   panelExpanded: 折叠/展开(默认展开,有默认筛选时方便看)
//   attrFiltersApplied: 实际生效的(传给 /change-heatmap),attrFilters 是用户编辑中
//   attrDirty: 两个状态不一致时显示 ● 未应用
// 2026-07-24: 属性筛选默认收起,品种部分默认展示 — header chevron 只控属性部分
//   (panelExpanded 保留 ref 备将来用;现以 attrExpanded 为准)
const panelExpanded = ref(false)
const attrExpanded = ref(false)
// 2026-07-24 删除: defaultCardsExpanded — 默认卡片折叠抽屉没了
const attrFiltersApplied = ref({})
const attrDirty = computed(() => {
  // 浅比较 entries(顺序无关,比较前排序)
  const sig = (o) => JSON.stringify(
    Object.entries(o).sort(([a], [b]) => a.localeCompare(b))
  )
  return sig(attrFilters.value) !== sig(attrFiltersApplied.value)
})

// v0.37: per-breed 独立 attr filters — 每个品种可单独配置筛选(避免共用筛选过滤掉其他品种)
//   attrFiltersByBreed: 用户编辑中,结构 { [breed]: { [key]: [values] } }
//   attrFiltersByBreedApplied: 已生效(同 attrFiltersApplied 分离,点击应用后才同步)
//   breedAttrDirty: 同 attrDirty,用于"应用"按钮 disabled 判断
const attrFiltersByBreed = ref({})
const attrFiltersByBreedApplied = ref({})
const breedAttrDirty = computed(() => {
  const sig = (o) => JSON.stringify(
    Object.entries(o).sort(([a, av], [b, bv]) => {
      // 双向排序:先 breed 名,再 attr key 名
      const cmpBreed = a.localeCompare(b)
      return cmpBreed !== 0 ? cmpBreed : String(a + '|' + Object.keys(av || {}).join(',')).localeCompare(b + '|' + Object.keys(bv || {}).join(','))
    })
  )
  return sig(attrFiltersByBreed.value) !== sig(attrFiltersByBreedApplied.value)
})
const breedAttrFilterTotal = computed(() => {
  let total = 0
  for (const breed in attrFiltersByBreed.value) {
    total += Object.values(attrFiltersByBreed.value[breed]).filter(vs => vs && vs.length > 0).length
  }
  return total
})
// v0.37: per-breed toggle — 不在这里调 loadHeatmap,统一交给 applyAttrFilters
function toggleBreedAttr(breed, key, value) {
  if (!attrFiltersByBreed.value[breed]) attrFiltersByBreed.value[breed] = {}
  if (!attrFiltersByBreed.value[breed][key]) attrFiltersByBreed.value[breed][key] = []
  const arr = attrFiltersByBreed.value[breed][key]
  const idx = arr.indexOf(value)
  if (idx >= 0) arr.splice(idx, 1)
  else arr.push(value)
  if (arr.length === 0) delete attrFiltersByBreed.value[breed][key]
  if (Object.keys(attrFiltersByBreed.value[breed]).length === 0) delete attrFiltersByBreed.value[breed]
  attrFiltersByBreed.value = { ...attrFiltersByBreed.value }
}
function clearBreedAttrFilters(breed) {
  delete attrFiltersByBreed.value[breed]
  attrFiltersByBreed.value = { ...attrFiltersByBreed.value }
}

// 2026-07-24 删除: isBreedSelected / toggleBreed — 搜索/卡片入口都没了,选品种全靠 loadRandomBreeds 自动完成
function removeBreed(breed) {
  const idx = selectedBreeds.value.indexOf(breed)
  if (idx >= 0) {
    selectedBreeds.value.splice(idx, 1)
    selectedBreeds.value = [...selectedBreeds.value]
    attrFilters.value = {}
    attrFiltersApplied.value = {}
    // v0.37: per-breed filters 同步
    attrFiltersByBreed.value = {}
    attrFiltersByBreedApplied.value = {}
    loadAttrKeys()
    loadHeatmap()
  }
}
// 2026-07-24 删除: clearAllBreeds — 清空品种按钮已删,选品种全靠 × 逐个删 + ↻ 重置(含 attr)兜底

// 已选筛选统计(v0.24 强制单选,每 k 最多 1 个 v,所以 attrFilterTotal = 有选的 k 数)
const attrFilterTotal = computed(() => {
  return Object.values(attrFilters.value).filter(vs => vs && vs.length > 0).length
})
const attrFilterSummary = computed(() => {
  const parts = []
  for (const [k, vs] of Object.entries(attrFilters.value)) {
    if (vs && vs.length) parts.push(`${k}=${vs[0]}`)
  }
  return parts.join(' + ')
})

// 2026-07-24 删除: 全部搜索/推荐/扩展品种相关函数
//   _searchDebounceTimer / onSearchInput / clearSearch / runBreedSearch /
//   selectBreedFromSearch / refreshRandomBreeds / loadExtendBreeds /
//   loadRecommendBreeds / visibleDefaultCards / refreshExtendBreeds /
//   addExtendToSelection
// 全部不再需要 — 页面已无搜索 UI,默认 12 品种由 loadAll 自动喂给 selectedBreeds
// 2026-07-24 删除: startResearch / clearSelectedBreed — 唯一作用就是调 clearAllBreeds,后者已删

const loading = ref(true)
const loadError = ref('')

// 热力图分块:每张表最多 HEATMAP_CHUNK_SIZE 个城市(默认 10,18 城拆 10+8=2 张)
// 后续如果城市数变多导致单张挤,可调小
const HEATMAP_CHUNK_SIZE = 10

// 单一热力图 grid 样式(给每块用):行标签 140px + N 列城市,min 48px,1fr 自动分摊
function chunkGridStyle(n) {
  return { gridTemplateColumns: `140px repeat(${n}, minmax(40px, 1fr))` }
}

// 把 breeds + cities + matrix 按城市切片成多张表
const heatmapChunks = computed(() => {
  const cities = heatmap.value.cities || []
  const breeds = heatmap.value.breeds || []
  const matrix = heatmap.value.matrix || []
  if (!cities.length) return []

  const size = HEATMAP_CHUNK_SIZE
  const chunks = []
  for (let i = 0; i < cities.length; i += size) {
    const end = Math.min(i + size, cities.length)
    const sliceCities = cities.slice(i, end)
    const sliceMatrix = matrix.map((row) => row.slice(i, end))
    chunks.push({
      key: `chunk-${i}`,
      cities: sliceCities,
      matrix: sliceMatrix,
      title: cities.length > size
        ? `城市 ${i + 1}–${end}（共 ${cities.length} 城 · 第 ${Math.floor(i / size) + 1} / ${Math.ceil(cities.length / size)} 张）`
        : null,
    })
  }
  return chunks
})

async function fetchJson(path) {
  // 页面级守卫: /market 页面只能调 /api/market/* 公开接口
  // 与 main.js 的 window.fetch 拦截器双保险(拦截器在前,这里在调用点最贴近报错位置)
  if (!path.startsWith('/api/market/')) {
    throw new Error(
      `[market-view-guard] /market 页面禁止调用 ${path}\n` +
      `  允许范围: /api/market/*`
    )
  }
  // 拼上 v=timestamp cache buster(如果 URL 有 v=)
  const finalPath = withCacheBuster(path)
  const r = await fetch(finalPath, { headers: { Accept: 'application/json' } })
  if (!r.ok) throw new Error(`${finalPath} → HTTP ${r.status}`)
  return r.json()
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    // 2026-07-24: 首屏拉 overview + 12 个默认随机品种 — 拉完直接喂给 selectedBreeds + 拉属性 + 渲染热力图
    const results = await Promise.allSettled([
      fetchJson('/api/market/overview'),
      fetchJson('/api/market/random-breeds').then(r => {
        const breeds = r.results || []
        const names = breeds.map(b => b.breed).filter(Boolean)
        if (names.length) {
          selectedBreeds.value = names
          // 品种变了 → 重置 attrs(同 toggleBreed 旧逻辑) + 拉属性键 + 渲染热力图
          attrFilters.value = {}
          attrFiltersApplied.value = {}
          attrFiltersByBreed.value = {}
          attrFiltersByBreedApplied.value = {}
          loadAttrKeys()
          loadHeatmap()
        }
      }),
    ])
    const [ov] = results
    if (ov.status === 'fulfilled') overview.value = ov.value

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

// 选品种(v0.28: 多选,onBreedChange 被 toggleBreed 替代,保留空函数兼容外部调用)
async function onBreedChange() {
  attrFilters.value = {}
  attrKeys.value = []
  if (!selectedBreeds.value.length) {
    await loadHeatmap()
    return
  }
  await loadAttrKeys()
  await loadHeatmap()
}

// v0.24: 单选 setAttrValue 已弃用(v0.29 改多选 toggle)
function setAttrValue(key, value) {
  if (attrFilters.value[key] && attrFilters.value[key][0] === value) {
    delete attrFilters.value[key]
  } else {
    attrFilters.value[key] = [value]
  }
  attrFilters.value = { ...attrFilters.value }
  loadHeatmap()
}

// v0.29: checkbox 多选 toggle — 不在这里 loadHeatmap,避免每点一下 reload
//   真正刷新交由 applyAttrFilters 触发(attrDirty 控制按钮可用性)
function toggleAttrValue(key, value) {
  if (!attrFilters.value[key]) attrFilters.value[key] = []
  const arr = attrFilters.value[key]
  const idx = arr.indexOf(value)
  if (idx >= 0) arr.splice(idx, 1)
  else arr.push(value)
  if (arr.length === 0) delete attrFilters.value[key]
  attrFilters.value = { ...attrFilters.value }
}

// v0.29: 应用属性筛选 — 把 attrFilters 拷给 attrFiltersApplied 后再 reload
function applyAttrFilters() {
  attrFiltersApplied.value = { ...attrFilters.value }
  // v0.37: per-breed applied 同步(深拷贝,因为结构嵌套)
  attrFiltersByBreedApplied.value = JSON.parse(JSON.stringify(attrFiltersByBreed.value))
  loadHeatmap()
}

// 2026-07-24 删除: selectAllDefault — 默认卡片面板没了,选品种全靠 loadAll 自动完成
function isAttrSelected(key, value) {
  return !!(attrFilters.value[key] && attrFilters.value[key].includes(value))
}
function clearAttrFilters() {
  attrFilters.value = {}
  attrFiltersApplied.value = {}
  // v0.37: 同时清 per-breed filters(共用筛选清空,独立筛选也一并清)
  attrFiltersByBreed.value = {}
  attrFiltersByBreedApplied.value = {}
  loadHeatmap()
}

// 重置
async function resetSelection() {
  // 2026-07-24: 搜索相关 state 清零已删 — 重置仅剩品种 + 属性
  selectedBreeds.value = []
  attrFilters.value = {}
  attrFiltersApplied.value = {}
  attrFiltersByBreed.value = {}
  attrFiltersByBreedApplied.value = {}
  attrKeys.value = []
  await loadHeatmap()
}

async function loadAttrKeys() {
  // 2026-07-24: 12 个默认品种属性不能遗漏 — 全部品种都进 breeds=A,B,C 聚合
  // (旧逻辑只用 selectedBreeds[0],v0.28 简化 UX,现在后端支持 terms 聚合,改回全量)
  if (!selectedBreeds.value.length) return
  loadingAttrKeys.value = true
  try {
    const breedsParam = selectedBreeds.value.join(',')
    const r = await fetchJson(
      `/api/market/attr-keys?breeds=${encodeURIComponent(breedsParam)}&limit_per_value=30`
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
  // v0.28: 多选 — 无品种直接返空
  if (!selectedBreeds.value.length) {
    heatmap.value = { breeds: [], cities: [], matrix: [] }
    return
  }
  // v0.28: 用 breeds=A,B,C 逗号分隔
  const params = [`breeds=${encodeURIComponent(selectedBreeds.value.join(','))}`]
  // v0.29: 用 attrFiltersApplied(应用后才生效),attrFilters 是编辑中状态
  //   attr_filters: 格式 k1:v1,v2;k2:v3 (AND 关系,各 k 至少 1 个匹配)
  const filterStr = Object.entries(attrFiltersApplied.value)
    .filter(([_, vs]) => vs && vs.length > 0)
    .map(([k, vs]) => `${k}:${vs.join(',')}`)
    .join(';')
  if (filterStr) {
    params.push(`attr_filters=${encodeURIComponent(filterStr)}`)
  }
  // v0.37: per-breed 独立筛选 'breed1=k:v;k:v||breed2=k:v'
  //   多个 breed 之间 || 分隔,内部 filters 用 ; 分隔(同 attr_filters 格式)
  //   breed 名要 encodeURIComponent(可能含中文/特殊字符)
  const breedFilterParts = []
  for (const [breed, filters] of Object.entries(attrFiltersByBreedApplied.value)) {
    const innerParts = []
    for (const [k, vs] of Object.entries(filters)) {
      if (vs && vs.length > 0) {
        innerParts.push(`${k}:${vs.join(',')}`)
      }
    }
    if (innerParts.length > 0) {
      breedFilterParts.push(`${encodeURIComponent(breed)}=${innerParts.join(';')}`)
    }
  }
  if (breedFilterParts.length > 0) {
    params.push(`breed_filters=${encodeURIComponent(breedFilterParts.join('||'))}`)
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

// 2026-07-24 删除: _onMarketDocMousedown — 搜索 dropdown 已删,点击外侧不再需要收起逻辑
// 2026-07-24 P0: 复用 /home 设计语言 — read-progress + 锚点滚动 + KPI 滚动数字
const readProgress = ref(0)
let _kpiObserver = null

function _onScrollForProgress() {
  const h = document.documentElement
  const max = h.scrollHeight - h.clientHeight
  readProgress.value = max > 0 ? Math.min(100, (window.scrollY / max) * 100) : 0
}

// KPI 数字滚动动画(进入视口触发,ease-out cubic)
const kpiAnimated = ref(false)
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

// 锚点滚动 + 回到顶部(Hero CTA + 数据来源按钮)
function scrollTo(id) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

// KPI 显示格式化:动画初期显 0(等动画接管) ,数据到位 + 动画完成后显真实值
function formatKpi(n) {
  if (n == null) return '—'
  if (kpiAnimated.value) return n.toLocaleString()
  return '0'
}

onMounted(() => {
  loadAll()
  // 2026-07-24 删除: mousedown click-outside 监听(搜索 dropdown 已删)

  // 2026-07-24 P0: 阅读进度条 + KPI 数字动画
  window.addEventListener('scroll', _onScrollForProgress, { passive: true })
  _onScrollForProgress()
  // 等 overview 数据 ready 后再激活 observer,确保 data-target 是真实值
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
  // 2026-07-24 删除: mousedown click-outside 监听清理
  // 2026-07-24 P0 cleanup
  window.removeEventListener('scroll', _onScrollForProgress)
  if (_kpiObserver) {
    _kpiObserver.disconnect()
    _kpiObserver = null
  }
})

// 2026-07-24 删除: 两条 dead watcher
//   - watch heatmap.breeds.length → loadExtendBreeds (extend 卡片面板已删)
//   - watch selectedBreeds.length → loadRecommendBreeds (推荐卡片面板已删)

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
.m-heatmap-search-wrap {
  display: inline-flex;
  align-items: center;
  position: relative;
  margin-left: 8px;
}
.m-heatmap-search {
  height: 36px;
  padding: 0 32px 0 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 14px;
  background: white;
  min-width: 240px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
  color: #111827;
}
.m-heatmap-search:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}
.m-heatmap-search::placeholder {
  color: #9ca3af;
}
.m-heatmap-search-clear {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  height: 24px;
  width: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  color: #6b7280;
  padding: 0;
}
.m-heatmap-search-clear:hover {
  background: #f3f4f6;
  color: #111827;
}
/* 2026-07-23 v0.26: 已选 chip 独立行(在输入上方)+ 美化输入 */
.m-selected-chip-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.m-selected-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 6px 5px 8px;
  background: linear-gradient(135deg, #dbeafe 0%, #e0e7ff 100%);
  border: 1px solid #93c5fd;
  border-radius: 8px;
  color: #1e40af;
  font-weight: 500;
  font-size: 12px;
  min-width: 0;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(59, 130, 246, 0.06);
}
.m-selected-chip-icon {
  font-size: 12px;
  flex-shrink: 0;
}
.m-selected-chip-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-selected-chip-sub {
  color: #6b7280;
  font-size: 12px;
  font-weight: normal;
  margin-left: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.m-selected-chip-clear {
  background: white;
  border: 1px solid #d1d5db;
  color: #6b7280;
  cursor: pointer;
  font-size: 12px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  line-height: 1;
  padding: 0;
  transition: all 0.1s;
}
.m-selected-chip-clear:hover {
  background: #fef2f2;
  border-color: #ef4444;
  color: #ef4444;
}

@keyframes m-breed-icon-loading {
  0%   { transform: rotate(0deg);   opacity: 0.65; }
  50%  { opacity: 1; }
  100% { transform: rotate(360deg); opacity: 0.65; }
}

/* 2026-07-23 v0.28 + v0.36: 多选 chips 区 — 改 grid 布局 + 紧凑 chip + 长名截断 */
.m-selected-chips-row {
  display: flex;
  flex-direction: column;                  /* v0.36: 列布局让 chips 网格 + 清空按钮各自占一行 */
  align-items: stretch;
  gap: 8px;
  margin-bottom: 10px;
  padding: 10px 12px;
  background: #eff6ff;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  max-height: 220px;
  overflow-y: auto;
}
.m-selected-chips-row::-webkit-scrollbar { width: 6px; }
.m-selected-chips-row::-webkit-scrollbar-thumb { background: #bfdbfe; border-radius: 3px; }
.m-selected-chips-label {
  font-size: 12px;
  color: #1e40af;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}
/* v0.36: 改 grid 布局 — 用 auto-fill + minmax 强制换列,避免 12 个 chip 挤一行 */
.m-selected-chips-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 6px;
  flex: 1;
  min-width: 0;
  align-items: center;
}
.m-selected-chips-filter {
  font-size: 12px;
  color: #4b5563;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 240px;
}

/* v0.24: 单选 radio button(原 m-attr-chip 多选) */
.m-attr-radio {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  font-size: 12px;
  cursor: pointer;
  user-select: none;
  background: white;
  transition: all 0.1s;
  white-space: nowrap;
}
.m-attr-radio:hover {
  border-color: #93c5fd;
  background: #f0f9ff;
}
.m-attr-radio.active {
  border-color: #3b82f6;
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 500;
}
.m-attr-radio input[type="radio"] {
  margin: 0;
  cursor: pointer;
  width: 12px;
  height: 12px;
  accent-color: #3b82f6;
}
.m-attr-radio-count {
  color: #9ca3af;
  font-size: 11px;
  margin-left: 2px;
}
.m-attr-radio.active .m-attr-radio-count {
  color: #3b82f6;
}

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

/* ── 热力图(2026-07-22:取消横向滚动,grid 自动收缩) ── */
.m-heatmap-scroll {
  overflow-x: hidden;          /* 不再产生横向滚动条 */
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}
.m-heatmap-grid {
  display: grid;
  gap: 2px;
  background: #f3f4f6;
  width: 100%;                 /* 占满容器,不再强制 min-width: 100% */
  font-size: 11px;
}
.m-heatmap-chunks {
  display: flex;
  flex-direction: column;
  gap: 14px;                   /* 多张表之间留 14px 间距 */
}
.m-heatmap-block { width: 100%; }
.m-heatmap-chunk-title {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
  margin-bottom: 6px;
  font-family: -apple-system, "PingFang SC", sans-serif;
}
.m-heatmap-cell {
  background: #fff;
  padding: 4px 6px;
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  font-weight: 600;
  font-size: 10px;             /* chunk 内每张表 ≤8 城,固定 10px 不需再缩 */
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  max-width: 120px;             /* 同步收窄,与 grid 140px 行标签适配 */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: -apple-system, "PingFang SC", sans-serif;
}
.m-row-meta {
  font-size: 10px;
  color: #9ca3af;
  margin-top: 2px;
  display: flex;
  flex-wrap: wrap;
  gap: 2px 4px;
  align-items: baseline;
  min-width: 0;
}
.m-meta-pri {
  color: #6b7280;
  font-weight: 500;
  letter-spacing: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.m-meta-pri.m-meta-fallback {
  color: #9ca3af;
  font-style: italic;
  font-weight: normal;
}
.m-meta-sub {
  color: #9ca3af;
  font-weight: 400;
  white-space: nowrap;
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
.m-footnote-warn {
  color: #b45309;
  background: #fef3c7;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

/* ── v0.29 ─ 折叠筛选面板 + 应用按钮 + pill / link ── */
.m-selection-panel {
  background: linear-gradient(180deg, #eff6ff 0%, #f0f9ff 100%);
  border: 1px solid #bfdbfe;
  border-radius: 12px;
  margin: 16px 0;
  overflow: hidden;
  transition: all 0.2s ease;
  box-shadow: 0 1px 2px rgba(30, 64, 175, 0.04);
}
.m-selection-panel.expanded {
  box-shadow: 0 6px 20px rgba(30, 64, 175, 0.12);
}
.m-selection-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;                      /* v0.35: 12→10 header 更紧凑 */
  gap: 12px;
  background: rgba(255, 255, 255, 0.6);
  border-bottom: 1px solid transparent;
  transition: border-color 0.2s ease;
  flex-wrap: wrap;                        /* v0.35: 允许换行,避免拥挤 */
}
.m-selection-panel.expanded .m-selection-panel-header {
  border-bottom-color: #bfdbfe;
}
.m-selection-panel-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: none;
  padding: 4px 8px;
  margin: -4px -8px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #1e40af;
  cursor: pointer;
  font-family: inherit;
  flex: 1;
  text-align: left;
  min-width: 0;                           /* v0.35: 允许收缩 */
}
.m-selection-panel-title:hover { background: rgba(255, 255, 255, 0.7); }
.m-panel-icon { font-size: 14px; }
.m-panel-title-text { font-weight: 700; }
.m-panel-chevron {
  color: #6b7280;
  font-size: 10px;
  margin-left: 4px;
}
.m-selection-panel-actions {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-shrink: 0;
}
.m-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  letter-spacing: 0;
  text-transform: none;
}
.m-pill-blue { background: #1e40af; color: #ffffff; }
.m-pill-warn {
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fcd34d;
}
.m-pill-good {
  background: #dcfce7;
  color: #166534;
  font-weight: 500;
}
.m-link-btn {
  background: white;
  border: 1px solid #d1d5db;
  color: #6b7280;
  cursor: pointer;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  font-family: inherit;
  white-space: nowrap;
  flex-shrink: 0;
  transition: all 0.15s ease;
}
.m-link-btn:hover {
  background: #f9fafb;
  border-color: #9ca3af;
  color: #111827;
}
.m-link-btn-danger { color: #6b7280; }
.m-link-btn-danger:hover {
  background: #fef2f2;
  border-color: #ef4444;
  color: #ef4444;
}
.m-selection-panel-body {
  padding: 14px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
/* v0.35: 摘要行 — 从 header 移到 body,pill 在这里 wrap 不会被 chevron 挤兑 */
.m-selection-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  padding-bottom: 10px;
  border-bottom: 1px dashed #dbeafe;
}
.m-selection-summary .m-pill {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 8px;
}
.m-selection-summary .m-pill::before {
  content: '';
  display: inline-block;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.5;
}

/* ── v0.29: 属性筛选 checkbox 多选 ── */
.m-attr-check {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  font-size: 12px;
  cursor: pointer;
  user-select: none;
  background: white;
  transition: all 0.1s;
  white-space: nowrap;
}
.m-attr-check:hover {
  border-color: #93c5fd;
  background: #f0f9ff;
}
.m-attr-check.active {
  border-color: #3b82f6;
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 600;
}
.m-attr-check input[type="checkbox"] {
  margin: 0;
  cursor: pointer;
  width: 12px;
  height: 12px;
  accent-color: #3b82f6;
}
.m-attr-check-count {
  color: #9ca3af;
  font-size: 11px;
  margin-left: 2px;
  font-weight: 500;
}
.m-attr-check.active .m-attr-check-count { color: #3b82f6; }
.m-apply-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #dbeafe;
  flex-wrap: wrap;
}
.m-apply-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border: 1px solid #d1d5db;
  background: #f3f4f6;
  color: #9ca3af;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: not-allowed;
  font-family: inherit;
  transition: all 0.15s ease;
}
.m-apply-btn.ready {
  background: linear-gradient(135deg, #1e40af 0%, #2563eb 100%);
  color: #ffffff;
  border-color: #1e40af;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(30, 64, 175, 0.25);
}
.m-apply-btn.ready:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(30, 64, 175, 0.35);
}
.m-apply-btn-icon { font-size: 14px; line-height: 1; }
.m-apply-hint { font-size: 11px; color: #6b7280; }

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
  .section-marker { padding: 0 16px; margin: 32px auto 16px; }
  .m-hero-ctas { gap: 8px; }
  .cta-button { padding: 10px 20px; font-size: 0.9rem; }
}

/* === 2026-07-24 P0: 复用 /home 设计语言(read-progress / section-marker / cta / kpi 动画 / 回到顶部) === */

/* 2026-07-24: 展开属性筛选按钮(收起态下替代 header 折叠,更直观) */
.m-attr-expand-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  margin: 12px 0 4px;
  background: rgba(59, 130, 246, 0.06);
  border: 1px dashed #93c5fd;
  border-radius: 8px;
  color: #1e40af;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s ease;
  font-family: inherit;
  font-weight: 500;
}
.m-attr-expand-btn:hover {
  background: rgba(59, 130, 246, 0.12);
  border-color: #3b82f6;
  border-style: solid;
  transform: translateY(-1px);
}
.m-attr-expand-icon {
  font-size: 11px;
  color: #3b82f6;
  transition: transform 0.2s ease;
}
.m-attr-expand-count {
  color: #3b82f6;
  font-weight: 600;
}

/* 阅读进度条(主色:#3b82f6 — 改成 /market 蓝调,不用 /home 青+红) */
.read-progress {
  position: fixed;
  top: 0;
  left: 0;
  height: 2px;
  background: linear-gradient(90deg, #3b82f6 0%, #1e40af 50%, #3b82f6 100%);
  z-index: 1000;
  transition: width 0.1s linear;
  box-shadow: 0 0 8px rgba(59, 130, 246, 0.5);
  pointer-events: none;
}

/* Section marker(01 OVERVIEW / 02 HEATMAP / 03 RECOMMEND / 04 SOURCE) */
/* 2026-07-24: 03 RECOMMEND 已删 — 默认 12 品种直接进热力图,不再需要推荐卡片 section */
.section-marker {
  display: flex;
  align-items: center;
  gap: 16px;
  max-width: 1200px;
  margin: 64px auto 24px;
  padding: 0 24px;
  scroll-margin-top: 80px;  /* 锚点跳转留 nav 空间 */
}
.section-num {
  font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', monospace;
  font-size: 14px;
  font-weight: 700;
  color: #3b82f6;
  letter-spacing: 0.05em;
}
.section-divider {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.4) 0%, transparent 100%);
}
.section-tagline {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  letter-spacing: 0.15em;
  text-transform: uppercase;
}

/* Hero CTA 按钮(浅底版 — 匹配 /market 白底设计,不用 /home 黑底霓虹) */
.cta-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 12px 28px;
  background: linear-gradient(135deg, #3b82f6 0%, #1e40af 100%);
  color: #fff;
  text-decoration: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.95rem;
  transition: transform 0.25s ease, box-shadow 0.25s ease;
  cursor: pointer;
  border: none;
  font-family: inherit;
  line-height: 1.2;
}
.cta-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 30px rgba(59, 130, 246, 0.3);
}
.cta-button.cta-secondary {
  background: transparent;
  color: #1e40af;
  border: 1px solid #d1d5db;
  box-shadow: none;
}
.cta-button.cta-secondary:hover {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.06);
}

/* Hero CTA 容器 */
.m-hero-ctas {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 28px;
}

/* KPI 单位后缀(城 / 个 / 条) */
.m-kpi-suffix {
  font-size: 0.55em;
  color: #6b7280;
  margin-left: 4px;
  font-weight: 500;
}

/* 回到顶部(跟 read-progress 配合:读到 100% 也可点) */
.m-back-to-top-wrap {
  display: flex;
  justify-content: center;
  margin: 40px 0 24px;
}
.m-back-to-top {
  padding: 10px 22px;
  background: transparent;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  color: #6b7280;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.25s ease;
  font-family: inherit;
}
.m-back-to-top:hover {
  color: #3b82f6;
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.06);
  transform: translateY(-1px);
}
</style>
