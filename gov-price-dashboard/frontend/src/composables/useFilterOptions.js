import { ref } from 'vue'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || '/api'

let _cache = null
let _cacheAt = 0
const CACHE_TTL = 60 * 1000  // 1 分钟（基本不变）

/**
 * 筛选下拉：城市/区县/分类选项
 * 一次性加载所有数据，前端筛选
 */
export function useFilterOptions() {
  const cityOptions = ref([])
  const countyOptions = ref([])
  const provinceCityMap = ref({})

  async function load(force = false) {
    if (!force && _cache && Date.now() - _cacheAt < CACHE_TTL) {
      cityOptions.value = _cache.cities || []
      countyOptions.value = _cache.counties || []
      provinceCityMap.value = _cache.provinceCityMap || {}
      return _cache
    }
    const { data } = await axios.get(`${API}/filter-options`)
    _cache = data || {}
    _cacheAt = Date.now()
    cityOptions.value = _cache.cities || []
    countyOptions.value = _cache.counties || []
    provinceCityMap.value = _cache.provinceCityMap || {}
    return _cache
  }

  return { cityOptions, countyOptions, provinceCityMap, load }
}

/**
 * 分类选项（来自 overview.by_category，独立 composable 以便单独刷新）
 */
export function useCategoryOptions() {
  const categoryOptions = ref([])

  function setFromOverview(byCategory = []) {
    categoryOptions.value = byCategory
      .map(c => ({ key: c.category, count: c.count, label: c.category }))
      .sort((a, b) => a.key.localeCompare(b.key, 'zh-CN'))
  }

  return { categoryOptions, setFromOverview }
}
