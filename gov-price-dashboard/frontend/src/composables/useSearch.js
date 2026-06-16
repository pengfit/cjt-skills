import { ref, computed, watch } from 'vue'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || '/api'

const HISTORY_KEY = 'gov_price_history'
const HISTORY_MAX = 10

/**
 * 搜索状态机：keyword / province / city / county / category / price range / page / sort
 * 内置 doSearch 防抖 + AbortController 取消上一请求
 */
export function useSearch() {
  const keyword = ref('')
  const province = ref('')
  const city = ref('')
  const county = ref('')
  const category = ref('')
  const priceMin = ref('')
  const priceMax = ref('')
  const page = ref(1)
  const pageSize = ref(20)
  const pageSizeOptions = [20, 50, 100]
  const jumpPage = ref(1)
  const sortKey = ref('')
  const sortDir = ref('asc')
  const debounceTimer = ref(null)

  const result = ref({})
  const loading = ref(false)
  const error = ref(false)

  let _abort = null

  async function doSearch(pageOverride) {
    if (_abort) _abort.abort()
    _abort = new AbortController()
    loading.value = true
    error.value = false
    try {
      const params = {}
      if (keyword.value.trim()) params.keyword = keyword.value.trim()
      if (province.value) params.province = province.value
      if (city.value) params.city = city.value
      if (county.value) params.county = county.value
      if (category.value) params.category = category.value
      if (priceMin.value) params.price_min = priceMin.value
      if (priceMax.value) params.price_max = priceMax.value
      params.page = Number(pageOverride || page.value)
      params.page_size = Number(pageSize.value)
      if (isNaN(params.page) || params.page < 1) params.page = 1

      const { data: res } = await axios.get(`${API}/search`, {
        params,
        signal: _abort.signal,
      })
      result.value = res || {}
      // 存搜索历史
      if (keyword.value.trim()) {
        addHistory(keyword.value.trim())
      }
    } catch (e) {
      if (axios.isCancel(e)) return
      error.value = true
      throw e
    } finally {
      loading.value = false
    }
  }

  function onKeywordInput() {
    if (debounceTimer.value) clearTimeout(debounceTimer.value)
    debounceTimer.value = setTimeout(() => doSearch(), 300)
  }

  function reset() {
    keyword.value = ''
    province.value = ''
    city.value = ''
    county.value = ''
    category.value = ''
    priceMin.value = ''
    priceMax.value = ''
    page.value = 1
    jumpPage.value = 1
    sortKey.value = ''
    sortDir.value = 'asc'
    result.value = {}
  }

  function sortBy(key) {
    if (sortKey.value === key) {
      sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortKey.value = key
      sortDir.value = 'asc'
    }
  }

  // 排序后派生数据
  const sortedData = computed(() => {
    const data = result.value.data || []
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

  // === 搜索历史（localStorage）===
  const history = ref(JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'))

  function addHistory(kw) {
    const filtered = history.value.filter(h => h !== kw)
    filtered.unshift(kw)
    history.value = filtered.slice(0, HISTORY_MAX)
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value)) } catch { /* ignore */ }
  }

  function clearHistory() {
    history.value = []
    try { localStorage.removeItem(HISTORY_KEY) } catch { /* ignore */ }
  }

  return {
    // state
    keyword, province, city, county, category,
    priceMin, priceMax,
    page, pageSize, pageSizeOptions, jumpPage,
    sortKey, sortDir,
    result, loading, error,
    history,
    // computed
    sortedData,
    // actions
    doSearch, onKeywordInput, reset, sortBy,
    addHistory, clearHistory,
  }
}
