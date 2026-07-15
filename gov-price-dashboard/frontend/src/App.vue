<template>
  <div class="dashboard with-sidebar" :class="{ 'mobile-sidebar-open': mobileSidebarOpen }">

    <!-- ========== SKIP LINK (a11y 2026-07-12 P2-3) ========== -->
    <a href="#main-content" class="skip-link">跳到主内容</a>

    <!-- ========== TOP BAR(统一 TopBar.vue) ========== -->
    <TopBar
      :overview="overview"
      :alerts="alerts"
      :last-refresh="lastRefresh"
      :last-refresh-ago="lastRefreshAgo"
      :polling-paused="pollingPaused"
      :poll-interval-min="POLL_INTERVAL_MS / 60000"
      @toggle-sidebar="mobileSidebarOpen = !mobileSidebarOpen"
      @open-cmd-palette="showCmdPalette = true"
      @go-health="goHealth"
      @go-list="goList"
      @toggle-polling="togglePollingPaused"
      @refresh-now="onRefreshNow"
    />

    <!-- ========== DASHBOARD BODY (sidebar + main) ========== -->
    <div class="dashboard-body">

    <!-- ========== SIDEBAR(统一 Sidebar.vue) ========== -->
    <Sidebar
      :groups="sidebarGroups"
      :current-tab="currentTab"
      :open="mobileSidebarOpen"
      @close="mobileSidebarOpen = false"
      @navigate="mobileSidebarOpen = false"
    />

    <!-- ========== MAIN CONTENT ========== -->
    <main id="main-content" class="main-content" tabindex="-1">

    <!-- 全部数据(list)tab — 抽到 ListView.vue(2026-07-13) -->
    <template v-if="currentTab === 'list'">
      <ListView
        :bundle="listSearch"
        :overview="overview"
        :category-panel-collapsed="categoryPanelCollapsed"
      />
    </template>

    <template v-if="currentTab === 'dist'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel">
        <DistributionChart
          :keyword="searchKeyword"
          :province="searchProvince"
          :city="searchCity"
        />
      </div>
    </template>

    <template v-if="currentTab === 'trend'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel"><PriceTrendView /></div>
    </template>

    <template v-if="currentTab === 'cockpit'">
      <div class="scroll-panel">
        <CockpitView />
      </div>
    </template>

    <template v-if="currentTab === 'category'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel"><CategoryView /></div>
    </template>

    <template v-if="currentTab === 'sync'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel"><SyncView /></div>
    </template>

    <template v-if="currentTab === 'health'">
      <div class="scroll-panel"><DataHealthView /></div>
    </template>

    <template v-if="currentTab === 'rules'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel"><VecRulesView /></div>
    </template>

    <template v-if="currentTab === 'taxonomy'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel"><CategoryTaxonomyView /></div>
    </template>

    </main>
    </div>
  </div>

  <!-- Toast: list 专属 toast 由 ListView.vue 内部渲染,这里不再重复 -->

  <!-- 命令面板 ⌘K -->
  <CmdPalette
    :show="showCmdPalette"
    :items="cmdItems"
    placeholder="搜索页面、命令... (⌘K)"
    @close="showCmdPalette = false"
    @select="onCmdSelect"
  />
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { defineAsyncComponent } from 'vue'
import axios from 'axios'
// D.2026-07-12 统一数字格式化
import { useFormatNumber } from './composables/useFormatNumber.js'
// P0-2 统一轮询：单一 tick 驱动 TopBar alerts + CockpitView data
import { useGlobalPolling } from './composables/useGlobalPolling.js'
// 2026-07-13 list 视图抽取(2026-07-13):ListView + useListSearch
import ListView from './components/ListView.vue'
import { useListSearch } from './composables/useListSearch.js'
// 路由级 view 全部 async(首屏不加载,切 tab 时才按需下载;2026-07-09 优化)
const DistributionChart = defineAsyncComponent(() => import('./components/DistributionChart.vue'))
const PriceTrendView = defineAsyncComponent(() => import('./components/PriceTrendView.vue'))
const CategoryView = defineAsyncComponent(() => import('./components/CategoryView.vue'))
const SyncView = defineAsyncComponent(() => import('./components/SyncView.vue'))
const DataHealthView = defineAsyncComponent(() => import('./components/DataHealthView.vue'))
const CockpitView = defineAsyncComponent(() => import('./components/CockpitView.vue'))
const VecRulesView = defineAsyncComponent(() => import('./components/VecRulesView.vue'))
const CategoryTaxonomyView = defineAsyncComponent(() => import('./components/CategoryTaxonomyView.vue'))
// 全局小工具(CmdPalette 始终挂载,保留 sync import)
import CmdPalette from './components/CmdPalette.vue'
import Sidebar from './components/layout/Sidebar.vue'
import TopBar from './components/layout/TopBar.vue'
import { TAB_ROUTES, legacyTabPath } from './router'

const route = useRoute()
const router = useRouter()
// D.2026-07-12 统一数字格式化
const fmt = useFormatNumber()
// 当前 tab key:来自路由 name,模板中自动解包
const currentTab = computed(() => route.name || 'cockpit')

const API = import.meta.env.VITE_API_URL || '/api'

// ============================================================
// STATE
// ============================================================
// 侧栏分组:复用 router/index.js 的 TAB_ROUTES,数字键 1-9 用 index 直接定位
// 新增 tab 只需改 router/index.js 一处
const TAB_ICONS = {
  cockpit: '🛸', list: '📋', category: '📁', dist: '📊',
  trend: '📈', sync: '🔄', health: '❤️', rules: '⚙️', taxonomy: '🏷️',
}
function sidebarItems(keys) {
  return TAB_ROUTES
    .map((r, idx) => ({ r, idx }))
    .filter(({ r }) => keys.includes(r.key))
    .map(({ r, idx }) => ({
      key: r.key,
      label: r.label,
      path: r.path,
      icon: TAB_ICONS[r.key] || '·',
      shortcut: String(idx + 1),  // 数字键 1-9 badge,跟全局键盘监听对齐
    }))
}
const sidebarGroups = computed(() => ([
  // 4 模块拆开(2026-07-10):数据浏览 + 数据采集 + 数据治理 + 价格可视化
  { key: 'view',    label: '数据浏览',    items: sidebarItems(['cockpit', 'list', 'category']) },
  { key: 'collect', label: '数据采集',    items: sidebarItems(['sync', 'health']) },
  { key: 'govern',  label: '数据治理',    items: sidebarItems(['rules', 'taxonomy']) },
  { key: 'viz',     label: '价格可视化',  items: sidebarItems(['dist', 'trend']) },
]))

const mobileSidebarOpen = ref(false)
const showCmdPalette = ref(false)  // ⌘K 命令面板
const categoryPanelCollapsed = ref(false)  // 分类面板收起
watch(() => route.name, () => { mobileSidebarOpen.value = false })  // 切 tab 后自动关闭移动侧边栏

// ⌘K 命令面板项(fix 2026-07-12 P3-batch2:加 group 分组)
const cmdItems = computed(() => {
  const navItems = TAB_ROUTES.map((t, i) => ({
    id: 'tab:' + t.key,
    group: '页面跳转',
    label: t.label,
    icon: ['🛩️', '📋', '📊', '📈', '🗺️', '🔄', '💚', '🧩', '🗂️'][i] || '·',
    hint: '跳转到 ' + t.label,
    shortcut: String(i + 1),
    action: () => router.push(t.path),
  }))
  const actionItems = [
    {
      id: 'search:open',
      group: '动作',
      label: '聚焦产品搜索',
      icon: '🔍',
      hint: '跳到"全部数据"页并聚焦搜索框',
      shortcut: '/',
      action: () => {
        router.push(legacyTabPath('list'))
        nextTick(() => document.querySelector('.filter-bar-input')?.focus())
      },
    },
    {
      id: 'drawer:open',
      group: '动作',
      label: '打开更多筛选',
      icon: '⚙️',
      hint: '弹出筛选抽屉(仅在"全部数据"生效)',
      action: () => { if (currentTab.value === 'list') listSearch.showDrawer.value = true },
    },
  ]
  // 数据查询:点击高分页可点击进 list 页
  const queryItems = overview.value && overview.value.by_province
    ? overview.value.by_province.slice(0, 5).map(p => ({
        id: 'prov:' + p.province,
        group: '数据查询',
        label: '查看 ' + p.province + ' 价格',
        icon: '🔎',
        hint: `${p.province} · ${fmt.count(p.count, '条记录')}`,
        action: () => router.push({ path: legacyTabPath('list'), query: { province: p.province } }),
      }))
    : []
  return [...navItems, ...actionItems, ...queryItems]
})

function onCmdSelect(item) {
  // 由组件内部调用 action,这里只处理额外逻辑
}
const overview = ref({ total_docs: 0, total_provinces: 0, total_cities: 0, avg_price: 0, max_price: 0, min_price: 0, by_province: [] })

// 数据新鲜度告警(2026-07-12 P1-4):来自 /api/skill-updates,15 分钟轮询
const alerts = ref({ count: 0, veryStaleCount: 0, updates: [] })
const lastRefresh = ref('')   // 接口响应的 ISO 时间,用于 tooltip
const lastRefreshAgo = ref('') // "3 分钟前" 等动态文案
let clockTimer = null

function togglePollingPaused() {
  pollingPaused.value = !pollingPaused.value
}

function onRefreshNow() {
  // 立即触发全局刷新:TopBar alerts 重新拉,CockpitView watch tick 同步刷新
  loadAlerts()
  bumpTick()
}

async function loadAlerts() {
  try {
    const d = await loadAPI(`${API}/skill-updates`)
    if (!d || !Array.isArray(d.updates)) return
    const updates = d.updates
    const nonFresh = updates.filter(u => u.status !== 'fresh')
    alerts.value = {
      count: nonFresh.length,
      veryStaleCount: nonFresh.filter(u => u.status === 'very_stale').length,
      updates,
    }
    if (d.now) lastRefresh.value = d.now
    refreshAgoText()  // 拿到 d.now 后立即刷一次,避免等 60s 定时器(2026-07-12 P1-4 fix)
  } catch (e) {
    // 静默失败:告警非关键路径,不要因网络抖动让顶栏报错
  }
}

function formatTimeAgo(iso) {
  if (!iso) return ''
  const dt = new Date(iso)
  if (isNaN(dt.getTime())) return ''
  const diffSec = Math.floor((Date.now() - dt.getTime()) / 1000)
  if (diffSec < 0) return '刚刚'
  if (diffSec < 60) return `${diffSec} 秒前`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  const diffDay = Math.floor(diffHour / 24)
  return `${diffDay} 天前`
}

function refreshAgoText() {
  lastRefreshAgo.value = lastRefresh.value ? `更新于 ${formatTimeAgo(lastRefresh.value)}` : ''
}

function goHealth() {
  router.push(legacyTabPath('health'))
}

// 顶栏 KPI 钻取（fix 2026-07-12 P3-batch1）：省份/城市可点击进 list 页
function goList(payload) {
  const scope = payload?.scope || 'all'
  // 当前 list 页用抽屉筛选驱动，scope 目前只置位，后续可扩展为预填筛选
  router.push({ path: legacyTabPath('list'), query: { _from: scope } })
}

// ============================================================
// API — 全局接口封装（Alerts/Overview/CityOptions 共用）
// ============================================================
async function loadAPI(url) {
  try { return (await axios.get(url)).data } catch { return {} }
}

// 内存缓存(避免重复请求)
let _overviewCache = null
let _overviewCacheAt = 0
let _filterOptionsCache = null
let _filterOptionsCacheAt = 0
const CACHE_TTL = 30 * 1000  // 30s

async function loadOverview() {
  if (_overviewCache && Date.now() - _overviewCacheAt < CACHE_TTL) {
    overview.value = _overviewCache
    return _overviewCache
  }
  const d = await loadAPI(`${API}/stats/overview`)
  _overviewCache = d || { total_docs: 0, total_provinces: 0, total_cities: 0, avg_price: 0, by_province: [] }
  _overviewCacheAt = Date.now()
  overview.value = _overviewCache
  return _overviewCache
}

async function loadCityOptions() {
  if (_filterOptionsCache && Date.now() - _filterOptionsCacheAt < CACHE_TTL) {
    cityOptions.value = _filterOptionsCache.cities || []
    countyOptions.value = _filterOptionsCache.counties || []
    provinceCityMap.value = _filterOptionsCache.provinceCityMap || {}
    return _filterOptionsCache
  }
  const d = await loadAPI(`${API}/filter-options`)
  _filterOptionsCache = d || {}
  _filterOptionsCacheAt = Date.now()
  if (_filterOptionsCache) {
    cityOptions.value = _filterOptionsCache.cities || []
    countyOptions.value = _filterOptionsCache.counties || []
    provinceCityMap.value = _filterOptionsCache.provinceCityMap || {}
  }
  return _filterOptionsCache
}

// ============================================================
// LIST 视图状态(2026-07-13 从 App.vue 抽出)
// useListSearch 内部 watch searchKeyword 会调 loadOverview 刷新顶栏 HUD。
// loadCityOptions 由 ListView 挂载后内部 useListSearch 负责调用。
// ============================================================
const cityOptions = ref([])
const countyOptions = ref([])
const provinceCityMap = ref({})

const listSearch = useListSearch({ router, loadOverview })
// 给顶层模板使用(DistributionChart 接收 list 筛选条件作为 props)。
// destructure 后 ref 在 setup scope 里自动 unwrap，模板可直接 searchKeyword。
const { searchKeyword, searchProvince, searchCity } = listSearch

// App 顶层 onMount：首屏 cockpit 需要 overview + filter-options。
// list tab 自己的 doSearch / loadCategoryOptions 由 useListSearch 内部负责。
onMounted(async () => {
  await Promise.all([loadOverview(), loadCityOptions()])
})


// P0-2 全局轮询: 单一 tick, TopBar alerts 与 CockpitView 共用
const { pollingTick, pollingPaused, startPolling, stopPolling, bumpTick, POLL_INTERVAL_MS } = useGlobalPolling()
watch(pollingTick, () => {
  // 暂停时不主动加载(保留节拍但不发请求, bpm 仍在走)
  if (!pollingPaused.value) loadAlerts()
})
onMounted(() => {
  loadAlerts()             // 首屏立刻拉一次
  startPolling()           // 启动全局 tick
  clockTimer = setInterval(refreshAgoText, 60 * 1000)
})
onBeforeUnmount(() => {
  stopPolling()
  if (clockTimer) clearInterval(clockTimer)
})

// Keyboard shortcuts
onMounted(() => {
  document.addEventListener('keydown', e => {
    // Esc 关闭所有层
    if (e.key === 'Escape') {
      listSearch.showColConfig.value = false
      if (listSearch.showDrawer.value) listSearch.showDrawer.value = false
      showCmdPalette.value = false
    }
    // ⌘K / Ctrl+K / / 打开命令面板
    const isInputFocused = e.target.matches && e.target.matches('input, textarea, select, [contenteditable]')
    if ((e.ctrlKey && e.key === 'k') || (e.metaKey && e.key === 'k')) {
      e.preventDefault()
      showCmdPalette.value = !showCmdPalette.value
      return
    }
    if (e.key === '/' && !isInputFocused) {
      e.preventDefault()
      showCmdPalette.value = true
      return
    }
    // 数字键 1-9 快速切换 tab(在非输入框中)
    if (!isInputFocused && !e.ctrlKey && !e.metaKey && !e.altKey && /^[1-9]$/.test(e.key)) {
      const tab = TAB_ROUTES[Number(e.key) - 1]
      if (tab) router.push(tab.path)
    }
  })
})

// ============================================================
</script>
