<!--
  DashboardView.vue (2026-07-19 拆分自 App.vue)

  拆分目的:
    旧 App.vue 的 setup() 无条件执行,即使 !isAuthed 也会跑所有 composables
    (useOverview / useGlobalPolling / 等),触发不必要的 API 请求。
    把 dashboard 部分独立成组件后,App.vue 用 v-if 真正懒挂载,
    未登录时不会触发任何 dashboard 数据请求。

  本组件假设调用方已鉴权(isAuthed=true),负责:
    - 顶栏/侧栏/主内容布局
    - 9 个 tab 的 v-if 切换
    - 全局轮询 / 告警 / 时间显示 / 键盘快捷键
-->
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

        <!-- 跨页详情中心 (2026-07-15 改造 A) — 走 currentTab === 'breed-detail' 路由 -->
        <template v-if="currentTab === 'breed-detail'">
          <BreedDetailView />
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

    <!-- 命令面板 ⌘K -->
    <CmdPalette
      :show="showCmdPalette"
      :items="cmdItems"
      placeholder="搜索页面、命令... (⌘K)"
      @close="showCmdPalette = false"
      @select="onCmdSelect"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { defineAsyncComponent } from 'vue'
import axios from 'axios'
// D.2026-07-12 统一数字格式化
import { useFormatNumber } from '../composables/useFormatNumber.js'
// P0-2 统一轮询：单一 tick 驱动 TopBar alerts + CockpitView data
import { useGlobalPolling } from '../composables/useGlobalPolling.js'
// 2026-07-13 list 视图抽取(2026-07-13):ListView + useListSearch
import ListView from './ListView.vue'
import { useListSearch } from '../composables/useListSearch.js'
// 路由级 view 全部 async(首屏不加载,切 tab 时才按需下载;2026-07-09 优化)
const DistributionChart = defineAsyncComponent(() => import('./DistributionChart.vue'))
const PriceTrendView = defineAsyncComponent(() => import('./PriceTrendView.vue'))
const CategoryView = defineAsyncComponent(() => import('./CategoryView.vue'))
const SyncView = defineAsyncComponent(() => import('./SyncView.vue'))
const DataHealthView = defineAsyncComponent(() => import('./DataHealthView.vue'))
const CockpitView = defineAsyncComponent(() => import('./CockpitView.vue'))
const VecRulesView = defineAsyncComponent(() => import('./VecRulesView.vue'))
const CategoryTaxonomyView = defineAsyncComponent(() => import('./CategoryTaxonomyView.vue'))

// 跨页详情中心 (2026-07-15 改造 A) — /breed-detail
const BreedDetailView = defineAsyncComponent(() => import('./BreedDetailView.vue'))
// 全局小工具(CmdPalette 始终挂载,保留 sync import)
import CmdPalette from './CmdPalette.vue'
import Sidebar from './layout/Sidebar.vue'
import TopBar from './layout/TopBar.vue'
import { TAB_ROUTES, legacyTabPath } from '../router'

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
  { key: 'view',    label: '数据浏览',    items: sidebarItems(['cockpit', 'list', 'category']) },
  { key: 'collect', label: '数据采集',    items: sidebarItems(['sync', 'health']) },
  { key: 'govern',  label: '数据治理',    items: sidebarItems(['rules', 'taxonomy']) },
  { key: 'viz',     label: '价格可视化',  items: sidebarItems(['dist', 'trend']) },
]))

const mobileSidebarOpen = ref(false)
const showCmdPalette = ref(false)
const categoryPanelCollapsed = ref(false)
watch(() => route.name, () => { mobileSidebarOpen.value = false })

// ⌘K 命令面板项
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
  const queryItems = overview.value && overview.value.by_province
    ? overview.value.by_province.slice(0, 5).map(p => ({
        id: 'prov:' + p.province,
        group: '数据查询',
        label: '查看 ' + p.province + '价格',
        icon: '🔎',
        hint: `${p.province} · ${fmt.count(p.count, '条记录')}`,
        action: () => router.push({ path: legacyTabPath('list'), query: { province: p.province } }),
      }))
    : []
  return [...navItems, ...actionItems, ...queryItems]
})

function onCmdSelect(item) {
  // 由组件内部调用 action
}
const overview = ref({ total_docs: 0, total_provinces: 0, total_cities: 0, avg_price: 0, max_price: 0, min_price: 0, by_province: [] })

const alerts = ref({ count: 0, veryStaleCount: 0, updates: [] })
const lastRefresh = ref('')
const lastRefreshAgo = ref('')
let clockTimer = null

function togglePollingPaused() {
  pollingPaused.value = !pollingPaused.value
}

function onRefreshNow() {
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
    refreshAgoText()
  } catch (e) {
    // 静默失败
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

function goList(payload) {
  const scope = payload?.scope || 'all'
  router.push({ path: legacyTabPath('list'), query: { _from: scope } })
}

// ============================================================
// API
// ============================================================
async function loadAPI(url) {
  try { return (await axios.get(url)).data } catch { return {} }
}

let _overviewCache = null
let _overviewCacheAt = 0
let _filterOptionsCache = null
let _filterOptionsCacheAt = 0
const CACHE_TTL = 30 * 1000

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

const cityOptions = ref([])
const countyOptions = ref([])
const provinceCityMap = ref({})

const listSearch = useListSearch({ router, loadOverview })
const { searchKeyword, searchProvince, searchCity } = listSearch

onMounted(async () => {
  await Promise.all([loadOverview(), loadCityOptions()])
})

// P0-2 全局轮询
const { pollingTick, pollingPaused, startPolling, stopPolling, bumpTick, POLL_INTERVAL_MS } = useGlobalPolling()
watch(pollingTick, () => {
  if (!pollingPaused.value) loadAlerts()
})
onMounted(() => {
  loadAlerts()
  startPolling()
  clockTimer = setInterval(refreshAgoText, 60 * 1000)
})
onBeforeUnmount(() => {
  stopPolling()
  if (clockTimer) clearInterval(clockTimer)
})

// Keyboard shortcuts
onMounted(() => {
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      listSearch.showColConfig.value = false
      if (listSearch.showDrawer.value) listSearch.showDrawer.value = false
      showCmdPalette.value = false
    }
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
    if (!isInputFocused && !e.ctrlKey && !e.metaKey && !e.altKey && /^[1-9]$/.test(e.key)) {
      const tab = TAB_ROUTES[Number(e.key) - 1]
      if (tab) router.push(tab.path)
    }
  })
})

const tabLoading = ref(false)
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--bg-primary, #f8fafc);
  color: var(--text-primary, #0f172a);
}
.skip-link {
  position: absolute;
  top: -100px;
  left: 8px;
  padding: 8px 14px;
  background: #2563eb;
  color: #fff;
  border-radius: 4px;
  text-decoration: none;
  z-index: 9999;
  transition: top 0.15s;
}
.skip-link:focus { top: 8px; }
.dashboard-body { display: flex; flex: 1; min-height: 0; }
.main-content {
  flex: 1;
  min-width: 0;
  padding: 20px 28px;
  overflow-y: auto;
  outline: none;
}
.scroll-panel { min-height: 100%; }
.tab-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 20px;
  color: #64748b;
  font-size: 14px;
}
.loading-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(100, 116, 139, 0.25);
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 768px) {
  .main-content { padding: 14px 16px; }
}
</style>