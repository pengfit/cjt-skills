import { ref } from 'vue'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || '/api'

/**
 * 总览数据：总量 + 省份/城市/分类分布
 * 内存缓存 30s，避免重复请求
 */
const CACHE_TTL = 30 * 1000
let _cache = null
let _cacheAt = 0

export function useOverview() {
  const overview = ref({
    total_docs: 0, total_provinces: 0, total_cities: 0,
    avg_price: 0, max_price: 0, min_price: 0,
    by_province: [], by_category: [],
  })
  const loading = ref(false)
  const error = ref('')

  async function load(force = false) {
    if (!force && _cache && Date.now() - _cacheAt < CACHE_TTL) {
      Object.assign(overview.value, _cache)
      return _cache
    }
    loading.value = true
    error.value = ''
    try {
      const { data } = await axios.get(`${API}/stats/overview`)
      const v = data || {}
      // 兼容字段
      if (!v.by_category && v.categories) v.by_category = v.categories
      Object.assign(overview.value, v)
      _cache = v
      _cacheAt = Date.now()
      return v
    } catch (e) {
      error.value = e.message || '加载失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  function invalidate() {
    _cache = null
    _cacheAt = 0
  }

  return { overview, loading, error, load, invalidate }
}
