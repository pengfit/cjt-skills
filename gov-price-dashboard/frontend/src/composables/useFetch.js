/**
 * useFetch.js — 统一 fetch composable(Step 2 / 3 架构重构)
 *
 * 设计动机:
 * - 6 个后台页(DataHealthView / VecRulesView / ListView / CockpitView / 等)
 *   各自手写 loading.value = true → axios.get → data.value = ... → catch → finally
 *   模式完全重复,80 行 boilerplate × 6 = 480 行冗余代码
 * - 错误处理不一致(有的 console.warn,有的 console.error,有的静默)
 * - loading 状态散落,不能复用(refresh / retry / 防抖)
 *
 * 设计:
 * - 用 axios 实例(继承 useApi.js 的全局拦截器:auth header + 401 自动跳登录)
 * - 返回 { data, loading, error, fetch, reset, lastFetchedAt } 5 个字段
 * - 每次 fetch 自动 abort 上一个未完成请求(防止 stale data 覆盖)
 * - error 不抛(吞到 ref),调用方判断 data 是不是 null 即可
 *
 * 用法:
 *   const { data, loading, error, fetch } = useFetch()
 *   const list = computed(() => data.value?.items ?? [])
 *   async function load() { await fetch('/api/stats/rules-vector', { params: { ... } }) }
 *
 * 注意:
 * - `api` 实例来自 ./useApi.js(已注册的 axios 拦截器,鉴权 + 401 跳登录)
 * - 不在这里新建 axios 实例,避免重复拦截器
 */
import { ref, shallowRef } from 'vue'
import { api } from './useApi.js'

export function useFetch() {
  // shallowRef:axios 返回的 JSON 大对象不需要深度响应式(性能)
  const data = shallowRef(null)
  const loading = ref(false)
  const error = ref(null)
  const lastFetchedAt = ref(null)

  // abort controller — 每次 fetch 取消上一个未完成请求,防 stale 覆盖
  let abortController = null

  /**
   * 发起一次请求
   * @param {string} url — 相对路径(/api/...)或绝对
   * @param {object} options — axios config:{ params / method / data / ... }
   * @returns {Promise<any|null>} — 成功返 data,失败/取消返 null
   */
  async function fetch(url, options = {}) {
    if (abortController) {
      try { abortController.abort() } catch (e) { /* noop */ }
    }
    abortController = new AbortController()

    loading.value = true
    error.value = null
    try {
      const res = await api.request({
        url,
        signal: abortController.signal,
        ...options,
      })
      data.value = res.data ?? null
      lastFetchedAt.value = Date.now()
      return data.value
    } catch (e) {
      // 用户主动 abort 不算 error
      if (e?.name === 'CanceledError' || e?.code === 'ERR_CANCELED') {
        return null
      }
      error.value = e
      // 401 已由 useApi.js 全局拦截器处理(跳登录); 这里只打 warn 留底
      console.warn('[useFetch]', e?.response?.status, url, e?.message || e)
      return null
    } finally {
      loading.value = false
    }
  }

  /** 重置状态 — 通常用于页面卸载 / 切换筛选大类 */
  function reset() {
    data.value = null
    error.value = null
    loading.value = false
    if (abortController) {
      try { abortController.abort() } catch (e) { /* noop */ }
      abortController = null
    }
    lastFetchedAt.value = null
  }

  return {
    data,
    loading,
    error,
    lastFetchedAt,
    fetch,
    reset,
  }
}