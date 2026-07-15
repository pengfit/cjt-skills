/**
 * 列表页搜索/筛选/排序/翻页 state + computed + actions(2026-07-13 重构)
 *
 * App.vue 原本 1391 行,list 视图占 ~600 行模板 + ~600 行脚本。
 * 抽到 composable 后,ListView.vue 仅负责模板渲染,业务逻辑全在 useListSearch。
 *
 * 共享外部依赖(参数注入,避免 composable 互相耦合):
 *   - router: vue-router 路由实例(syncToQuery / restoreFromQuery 用)
 *   - loadOverview: 跨 tab 副作用——筛选条件变化时刷新顶栏 HUD 概览
 *
 * 返回值是一个 bundle 对象(ref + computed + actions + DOM ref),
 * ListView 模板直接 `v-model="bundle.searchKeyword"` / `@click="bundle.doSearch"`。
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import axios from 'axios'
import { exportCsvAsFile, withTimestamp } from './useExport.js'
// P2-15:历史模块拆分
import { useSearchHistory } from './useSearchHistory.js'
import { useFormatNumber } from './useFormatNumber.js'

export function useListSearch({ router, loadOverview }) {
  const fmt = useFormatNumber()
  const API = import.meta.env.VITE_API_URL || '/api'

  // ============================================================
  // STATE — 筛选
  // ============================================================
  const searchKeyword = ref('')
  const searchProvince = ref('')
  const searchCity = ref('')
  const searchCounty = ref('')
  const searchCategoryCode = ref('')
  const searchCategoryLevel = ref('')
  const categoryOptions = ref([])
  const priceMin = ref('')
  const priceMax = ref('')
  const dateFrom = ref('')
  const dateTo = ref('')
  const dateRangeKey = ref('all')
  const datePresets = [
    { key: 'all',    label: '全部' },
    { key: '7d',     label: '近 7 天' },
    { key: '30d',    label: '近 30 天' },
    { key: '90d',    label: '近 90 天' },
    { key: 'ytd',    label: '今年' },
  ]
  const pricePresets = [
    { label: '0-500',    min: '0',    max: '500' },
    { label: '500-2k',   min: '500',  max: '2000' },
    { label: '2k-1万',  min: '2000', max: '10000' },
    { label: '>1万',    min: '10000', max: '' },
  ]
  const categoryBreadcrumb = ref([])

  // ============================================================
  // STATE — 列表 / 翻页 / 加载
  // ============================================================
  const searchResult = ref({})
  const searchPage = ref(1)
  const jumpPage = ref(1)
  const pageSize = ref(20)
  const pageSizeOptions = [20, 50, 100]
  const loading = ref(true)
  const searchError = ref(false)
  const debounceTimer = ref(null)

  // 筛选选项(省份/城市/区县) — 由 App.vue loadCityOptions 共享注入
  const cityOptions = ref([])
  const countyOptions = ref([])
  const provinceCityMap = ref({})

  // ============================================================
  // STATE — 排序 / 展开
  // ============================================================
  const sortKey = ref('')
  const sortDir = ref('asc')
  const expandedRow = ref(null)
  function toggleRow(item, idx) {
    const key = item.id || idx
    expandedRow.value = expandedRow.value === key ? null : key
  }

  // ============================================================
  // STATE — 历史 / 列配置 / 抽屉 / Toast
  // ============================================================
  // P2-15:抽到 useSearchHistory
  const { history: searchHistory, add: addHistory, clear: clearHistoryFn } = useSearchHistory()
  const allColumns = ref([
    { key: 'breed',    label: '产品名称',  sortable: true,  visible: true, width: 180 },
    { key: 'price',    label: '价格',      sortable: true,  visible: true, width: 140 },
    { key: 'attr',     label: '属性',      sortable: false, visible: false, width: 220 },
    { key: 'unit',     label: '单位',      sortable: false, visible: true, width: 60  },
    { key: 'date',     label: '日期',      sortable: true,  visible: true, width: 95  },
    { key: 'category', label: '分类',      sortable: true,  visible: true, width: 120 },
  ])
  const showColConfig = ref(false)
  const showDrawer = ref(false)
  const colConfigRef = ref(null)
  const toast = ref({ show: false, msg: '', type: 'info' })

  // ============================================================
  // COMPUTED
  // ============================================================
  const visibleColumns = computed(() => allColumns.value.filter(c => c.visible))

  const filteredCities = computed(() => {
    if (!searchProvince.value) return cityOptions.value
    return cityOptions.value.filter(c => c.province === searchProvince.value)
  })

  const filteredCounties = computed(() => {
    let list = countyOptions.value
    if (searchProvince.value) list = list.filter(c => c.province === searchProvince.value)
    if (searchCity.value) list = list.filter(c => c.city === searchCity.value)
    return list
  })

  const sortedData = computed(() => {
    const data = searchResult.value.data || []
    if (!sortKey.value) return data
    return [...data].sort((a, b) => {
      let av = a[sortKey.value] ?? ''
      let bv = b[sortKey.value] ?? ''
      av = String(av).toLowerCase()
      bv = String(bv).toLowerCase()
      if (av < bv) return sortDir.value === 'asc' ? -1 : 1
      if (av > bv) return sortDir.value === 'asc' ? 1 : -1
      return 0
    })
  })

  const pageStart = computed(() => {
    const s = (Number(searchPage.value) - 1) * pageSize.value + 1
    return s > 0 ? fmt.int(s) : '0'
  })

  const pageEnd = computed(() => {
    const e = Math.min(Number(searchPage.value) * pageSize.value, searchResult.value.total || 0)
    return fmt.int(e)
  })

  const pageRange = computed(() => {
    const total = searchResult.value.pages || 1
    const cur = Number(searchPage.value)
    if (total <= 7) {
      return Array.from({length: total}, (_, i) => i + 1)
    }
    const range = []
    if (cur <= 4) {
      for (let i = 1; i <= 5; i++) range.push(i)
      range.push('...')
      range.push(total)
    } else if (cur >= total - 3) {
      range.push(1)
      range.push('...')
      for (let i = total - 4; i <= total; i++) range.push(i)
    } else {
      range.push(1)
      range.push('...')
      for (let i = cur - 1; i <= cur + 1; i++) range.push(i)
      range.push('...')
      range.push(total)
    }
    return range
  })

  // ============================================================
  // ACTIONS — 排序 / 翻页
  // ============================================================
  function sortBy(key) {
    if (sortKey.value === key) {
      sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortKey.value = key
      sortDir.value = 'asc'
    }
  }

  function onPageSizeChange() {
    searchPage.value = '1'
    jumpPage.value = 1
    doSearch(1)
  }

  function prevPage() {
    if (searchPage.value <= 1) return
    searchPage.value = String(Number(searchPage.value) - 1)
    doSearch(Number(searchPage.value))
  }

  function nextPage() {
    if (searchPage.value >= searchResult.value.pages) return
    searchPage.value = String(Number(searchPage.value) + 1)
    doSearch(Number(searchPage.value))
  }

  function goToPage(p) {
    const maxPage = searchResult.value.pages || 1
    if (p < 1 || p > maxPage) {
      showToast(`页码超出范围,当前仅第 1-${maxPage} 页`)
      return
    }
    searchPage.value = String(p)
    doSearch(Number(searchPage.value))
  }

  // ============================================================
  // ACTIONS — 筛选 / 重置
  // ============================================================
  function onCityChange() {
    searchCounty.value = ''
    // 不自动搜索,等用户点击「确定」
  }

  function onProvinceChange() {
    searchCity.value = ''
    searchCounty.value = ''
  }

  function onCategoryTreeSelect(node) {
    if (node.l3) {
      searchCategoryCode.value = node.l3
      searchCategoryLevel.value = 'l3'
      const parents = (node.parentPath || []).map(p => ({ code: p.code, name: p.name || p.code }))
      categoryBreadcrumb.value = [...parents, { code: node.l3, name: node.name_l3 || node.l3 }]
    } else if (node.l2) {
      searchCategoryCode.value = node.l2
      searchCategoryLevel.value = 'l2'
      const parents = (node.parentPath || []).map(p => ({ code: p.code, name: p.name || p.code }))
      categoryBreadcrumb.value = [...parents, { code: node.l2, name: node.name_l2 || node.l2 }]
    } else if (node.l1) {
      searchCategoryCode.value = node.l1
      searchCategoryLevel.value = 'l1'
      categoryBreadcrumb.value = [{ code: node.l1, name: node.name_l1 || node.l1 }]
    }
    doSearch()
  }

  function resetSearch() {
    searchKeyword.value = ''
    searchProvince.value = ''
    searchCity.value = ''
    searchCounty.value = ''
    searchCategoryCode.value = ''
    searchCategoryLevel.value = ''
    categoryBreadcrumb.value = []
    priceMin.value = ''
    priceMax.value = ''
    dateFrom.value = ''
    dateTo.value = ''
    dateRangeKey.value = 'all'
    searchPage.value = '1'
    jumpPage.value = 1
    sortKey.value = ''
    sortDir.value = 'asc'
    searchResult.value = {}
  }

  function onKeywordInput() {
    if (debounceTimer.value) clearTimeout(debounceTimer.value)
    debounceTimer.value = setTimeout(() => doSearch(), 300)
  }

  function isPresetActive(preset) {
    return priceMin.value === preset.min && priceMax.value === preset.max
  }

  function applyPreset(preset) {
    priceMin.value = preset.min
    priceMax.value = preset.max
    // 不自动搜索,等用户点击「确定」
  }

  function expandRange() {
    priceMin.value = ''
    priceMax.value = ''
  }

  // P2-15:直接调 composable 的 clear
  function clearHistory() {
    clearHistoryFn()
  }

  function applyDatePreset(preset) {
    dateRangeKey.value = preset.key
    const today = new Date()
    const _fmt = d => d.toISOString().slice(0, 10)
    dateTo.value = _fmt(today)
    if (preset.key === 'all') {
      dateFrom.value = ''
      dateTo.value = ''
    } else if (preset.key === '7d') {
      dateFrom.value = _fmt(new Date(today.getTime() - 7 * 86400000))
    } else if (preset.key === '30d') {
      dateFrom.value = _fmt(new Date(today.getTime() - 30 * 86400000))
    } else if (preset.key === '90d') {
      dateFrom.value = _fmt(new Date(today.getTime() - 90 * 86400000))
    } else if (preset.key === 'ytd') {
      dateFrom.value = `${today.getFullYear()}-01-01`
    }
  }

  function toggleColConfig() {
    showColConfig.value = !showColConfig.value
  }

  // ============================================================
  // ACTIONS — 搜索主流程 + URL 同步
  // ============================================================
  async function doSearch(pageOverride) {
    if (!pageOverride) {
      searchPage.value = '1'
      jumpPage.value = 1
      sortKey.value = ''
      sortDir.value = 'asc'
    }
    loading.value = true
    searchError.value = false
    try {
      const params = {}
      if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
      if (searchProvince.value) params.province = searchProvince.value
      if (searchCity.value) params.city = searchCity.value
      if (searchCounty.value) params.county = searchCounty.value
      if (searchCategoryCode.value && searchCategoryLevel.value) {
        const levelKey = 'category_' + searchCategoryLevel.value
        params[levelKey] = searchCategoryCode.value
      }
      if (priceMin.value) params.price_min = priceMin.value
      if (priceMax.value) params.price_max = priceMax.value
      if (dateFrom.value) params.date_from = dateFrom.value
      if (dateTo.value) params.date_to = dateTo.value
      params.page = Number(pageOverride || searchPage.value)
      params.page_size = Number(pageSize.value)
      if (isNaN(params.page) || params.page < 1) params.page = 1

      const { data: res } = await axios.get(`${API}/search`, { params })
      searchResult.value = res || {}

      syncToQuery()

      if (searchKeyword.value.trim()) {
        const kw = searchKeyword.value.trim()
        addHistory(kw)  // P2-15:走 composable,内部去重+trim+localStorage
      }
    } catch (e) {
      searchError.value = true
      showToast('请求失败:' + (e.message || '网络错误'))
    } finally {
      loading.value = false
    }
  }

  function readQueryFromLocation() {
    const sp = new URLSearchParams(window.location.search)
    const out = {}
    for (const [k, v] of sp.entries()) out[k] = v
    return out
  }

  function restoreFromQuery() {
    const q = readQueryFromLocation()
    if (q.keyword) searchKeyword.value = String(q.keyword)
    if (q.province) searchProvince.value = String(q.province)
    if (q.city) searchCity.value = String(q.city)
    if (q.county) searchCounty.value = String(q.county)
    if (q.category_code) {
      searchCategoryCode.value = String(q.category_code)
      searchCategoryLevel.value = String(q.category_level || 'l3')
    }
    if (q.date_from || q.date_to) {
      if (q.date_from) dateFrom.value = String(q.date_from)
      if (q.date_to) dateTo.value = String(q.date_to)
      dateRangeKey.value = 'custom'
    } else if (dateRangeKey.value === 'all' && !dateFrom.value && !dateTo.value) {
      applyDatePreset({ key: '7d', label: '近 7 天' })
    }
    if (q.price_min) priceMin.value = String(q.price_min)
    if (q.price_max) priceMax.value = String(q.price_max)
  }

  function syncToQuery() {
    const q = {}
    if (searchKeyword.value.trim()) q.keyword = searchKeyword.value.trim()
    if (searchProvince.value) q.province = searchProvince.value
    if (searchCity.value) q.city = searchCity.value
    if (searchCounty.value) q.county = searchCounty.value
    if (searchCategoryCode.value) {
      q.category_code = searchCategoryCode.value
      q.category_level = searchCategoryLevel.value
    }
    if (priceMin.value) q.price_min = priceMin.value
    if (priceMax.value) q.price_max = priceMax.value
    if (dateFrom.value) q.date_from = dateFrom.value
    if (dateTo.value) q.date_to = dateTo.value
    router.replace({ query: q }).catch(() => {})
  }

  // ============================================================
  // ACTIONS — 格式化辅助 (列表渲染用)
  // ============================================================
  function highlightKeyword(text) {
    if (!text || !searchKeyword.value.trim()) return text
    const kw = searchKeyword.value.trim()
    const regex = new RegExp(`(${kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
    return String(text).replace(regex, '<span class="breed-match">$1</span>')
  }

  function fmtCell(v) {
    if (v === null || v === undefined || v === '') return '--'
    const n = Number(v)
    if (isNaN(n)) return v
    return fmt.price(n).replace('¥', '')
  }

  function getPriceClass(price, avgPrice) {
    if (price === null || price === undefined || price === '' || String(price).trim() === '') return 'no-price'
    const n = Number(price)
    if (isNaN(n) || !avgPrice) return ''
    if (n > avgPrice * 1.5) return 'price-high'
    if (n < avgPrice * 0.5) return 'price-low'
    return ''
  }

  function getPriceBadge(item) {
    const n = Number(item.price)
    const av = Number(item.avg_price)
    if (isNaN(n) || !av) return null
    if (n > av * 2) return { text: '异常高', cls: 'badge-danger' }
    if (n > av * 1.5) return { text: '偏高', cls: 'badge-warning' }
    if (n < av * 0.5) return { text: '异常低', cls: 'badge-blue' }
    return null
  }

  function getTaxDiffBadge(item) {
    const p = Number(item.price)
    const tp = Number(item.tax_price)
    if (isNaN(p) || isNaN(tp) || p <= 0) return null
    const diff = (tp - p) / p
    if (diff > 0.2) return '含税溢价 ' + (diff * 100).toFixed(0) + '%'
    return null
  }

  function getPriceChange(item) {
    const n = Number(item.price)
    const prev = Number(item.prev_price)
    if (isNaN(n) || isNaN(prev) || prev <= 0) return null
    const pct = ((n - prev) / prev) * 100
    const sign = pct >= 0 ? '+' : ''
    const arrow = pct >= 0 ? '↑' : '↓'
    return {
      text: `${sign}${pct.toFixed(1)}%`,
      cls: pct >= 0 ? 'change-up' : 'change-down'
    }
  }

  function getCellClass(key, item) {
    if (key === 'price') return 'price-cell ' + getPriceClass(item.price, item.avg_price)
    if (key === 'tax_price') return 'tax-price-cell'
    if (key === 'unit') return 'unit-cell'
    if (key === 'date') return 'date-cell'
    if (key === 'spec') return 'td-spec'
    if (key === 'province') return 'td-province'
    if (key === 'city') return 'td-city'
    if (key === 'county') return 'td-county'
    return ''
  }

  function isStale(dateStr) {
    if (!dateStr) return false
    const d = new Date(dateStr)
    const now = new Date()
    const diff = (now - d) / (1000 * 60 * 60 * 24)
    return diff > 30
  }

  function staleText(dateStr) {
    if (!dateStr) return ''
    const d = new Date(dateStr)
    const now = new Date()
    const diff = Math.floor((now - d) / (1000 * 60 * 60 * 24))
    if (diff > 60) return `🕐 ${Math.floor(diff / 30)}个月前`
    if (diff > 30) return `🕐 ${diff}天前`
    return ''
  }

  // ============================================================
  // ACTIONS — Toast / 点击外部关闭
  // ============================================================
  function showToast(msg, type = 'info') {
    toast.value = { show: true, msg, type }
    setTimeout(() => { toast.value.show = false }, 3000)
  }

  function handleDocClick(e) {
    if (colConfigRef.value && !colConfigRef.value.contains(e.target)) {
      showColConfig.value = false
    }
  }

  // ============================================================
  // ACTIONS — 导出 CSV
  // ============================================================
  function exportSearchResultCsv() {
    if (!sortedData.value.length) return
    const cols = visibleColumns.value
    const header = cols.map(c => c.label)
    const rows = [header]
    for (const item of sortedData.value) {
      const row = cols.map(c => {
        const v = item[c.key]
        if (v == null) return ''
        if (typeof v === 'object') return JSON.stringify(v)
        return String(v)
      })
      rows.push(row)
    }
    const fname = `搜索结果-${searchKeyword.value || '全部'}-${withTimestamp()}.csv`
    exportCsvAsFile(rows, fname)
  }

  function exportCurrentPage() {
    const headers = visibleColumns.value.map(c => c.label).join(',')
    const rows = sortedData.value.map(item =>
      visibleColumns.value.map(c => {
        const val = item[c.key]
        return typeof val === 'string' && val.includes(',') ? `"${val}"` : (val ?? '')
      }).join(',')
    ).join('\n')
    const csv = '\uFEFF' + headers + '\n' + rows
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `建材价格_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
    showToast(`已导出 ${sortedData.value.length} 条数据`)
  }

  // ============================================================
  // API — 分类选项(独立缓存,与 overview 解耦)
  // ============================================================
  let _categoryCache = null
  let _categoryCacheAt = 0
  async function loadCategoryOptions() {
    const CATEGORY_TTL = 60 * 1000
    if (_categoryCache && Date.now() - _categoryCacheAt < CATEGORY_TTL) {
      categoryOptions.value = _categoryCache
      return
    }
    try {
      const d = (await axios.get(`${API}/stats/categories?size=500`)).data
      const list = (d?.data || []).map(c => ({ key: c.key, count: c.count, label: c.key }))
        .sort((a, b) => a.key.localeCompare(b.key, 'zh-CN'))
      _categoryCache = list
      _categoryCacheAt = Date.now()
      categoryOptions.value = list
    } catch {
      // 静默失败:分类选项非关键路径
    }
  }

  // ============================================================
  // LIFECYCLE — 跨 tab 副作用 + 事件绑定 + list tab 初始化
  // ============================================================
  // 筛选条件变化 → 刷顶栏 HUD 概览(跨 tab)
  watch(
    [searchKeyword, searchProvince, searchCity, priceMin, priceMax],
    async () => {
      if (Object.keys(searchResult.value).length) {
        await loadOverview()
      }
    }
  )

  // list tab 挂载时初始化：从 URL 恢复筛选 → 加载分类选项 → 首查
  // loadCityOptions 是 App 层共享的（页脚下拉依赖），不在这里重复调用。
  onMounted(async () => {
    restoreFromQuery()
    await loadCategoryOptions()
    await doSearch()
    document.addEventListener('click', handleDocClick)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('click', handleDocClick)
  })

  // ============================================================
  // RETURN — bundle(模板/外部消费)
  // ============================================================
  return {
    // refs
    searchKeyword, searchProvince, searchCity, searchCounty,
    searchCategoryCode, searchCategoryLevel, categoryOptions,
    priceMin, priceMax, dateFrom, dateTo, dateRangeKey, datePresets,
    pricePresets, categoryBreadcrumb,
    searchResult, searchPage, jumpPage, pageSize, pageSizeOptions,
    loading, searchError, debounceTimer,
    cityOptions, countyOptions, provinceCityMap,
    sortKey, sortDir, expandedRow,
    searchHistory, allColumns, showColConfig, showDrawer, colConfigRef,
    toast,
    // computed
    visibleColumns, filteredCities, filteredCounties, sortedData,
    pageStart, pageEnd, pageRange,
    // actions
    sortBy, onPageSizeChange, prevPage, nextPage, goToPage,
    onCityChange, onProvinceChange, onCategoryTreeSelect, resetSearch,
    onKeywordInput, isPresetActive, applyPreset, expandRange, clearHistory,
    applyDatePreset, toggleColConfig,
    doSearch, restoreFromQuery, syncToQuery,
    highlightKeyword, fmtCell,
    getPriceClass, getPriceBadge, getTaxDiffBadge, getPriceChange,
    getCellClass, isStale, staleText,
    showToast, handleDocClick,
    exportSearchResultCsv, exportCurrentPage,
    loadCategoryOptions,
    toggleRow,
  }
}