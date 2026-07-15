import { ref } from 'vue'

const STORAGE_KEY = 'gov_price_history'
const MAX_HISTORY = 10

/**
 * P2-15:搜索历史(从 useListSearch 拆出)
 *
 * - localStorage 持久化
 * - 最大 10 条,fifo 去重
 * - add() 时去重并 trim 到 MAX_HISTORY
 * - clear() 时清空 localStorage
 */
export function useSearchHistory() {
  const history = ref(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'))

  function _persist() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(history.value))
  }

  function add(keyword) {
    if (!keyword || !keyword.trim()) return
    const kw = keyword.trim()
    history.value = [kw, ...history.value.filter(h => h !== kw)].slice(0, MAX_HISTORY)
    _persist()
  }

  function remove(keyword) {
    history.value = history.value.filter(h => h !== keyword)
    _persist()
  }

  function clear() {
    history.value = []
    try { localStorage.removeItem(STORAGE_KEY) } catch (_) {}
  }

  return {
    history,
    add,
    remove,
    clear,
    MAX_HISTORY,
  }
}
