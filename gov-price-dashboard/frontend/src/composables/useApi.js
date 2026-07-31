/** axios 拦截器(2026-07-19) — 装在全局 axios 上,所有用 axios 的地方都生效
 *
 * - request:  自动加 Authorization: Bearer <jwt>
 *             + 2026-07-31: /market 公开页守卫 — 只放行 /api/market/* (XHR 路径,
 *               window.fetch 钩子拦不到 axios,必须在这里再拦一遍)
 * - response: 401 时清 token + 跳 /login?next=...
 *
 * 注意:必须 import 这个文件才能注册拦截器。main.js 已 import。
 */
import axios from 'axios'
import { getToken } from './useAuth.js'

const API = import.meta.env.VITE_API_URL || '/api'
const TOKEN_KEY = '***'
const USER_KEY = '***'

// ── /market 公开页守卫 (2026-07-31 新增) ──────────────────
//   隔离范围: /market 路由下,任何 /api/* 调用必须以 /api/market/ 开头,其他全部 reject
//   必须在 main.js 的 window.fetch 钩子之外再装一遍 — axios 走 XMLHttpRequest,
//   window.fetch 钩子拦不到。两处放行白名单必须保持一致(都用 isMarketAllowed)。
//   公开页白名单收紧到 /api/market/* (2026-07-28 v3 后趋势卡也走 /api/market/{price-trend,trend-table},
//   /api/norm/* 已无人调用 — 顺手从 main.js 白名单也删掉)
export function isMarketRoute() {
  if (typeof window === 'undefined') return false
  const p = window.location.pathname
  return p === '/market' || p.startsWith('/market/')
}

export function isMarketAllowed(url) {
  if (!url) return false
  return url.includes('/api/market/')
}

// ── 拦截器(全局 axios)────────────────────────────────────────
axios.interceptors.request.use((cfg) => {
  // 1) /market 公开页守卫 — 拦 axios XHR 调用( window.fetch 钩子管不到这里)
  if (isMarketRoute()) {
    const url = cfg.url || ''
    const isApiCall = url.includes('/api/')
    if (isApiCall && !isMarketAllowed(url)) {
      console.warn(
        `[market-guard] /market 页面拒绝调用 ${url}` +
        '\n  原因:该接口不属于 /market 范畴,防止数据层污染'
      )
      return Promise.reject(new Error(`market-guard blocked (axios): ${url}`))
    }
  }
  // 2) 鉴权头
  const t = getToken()
  if (t && !cfg.headers.Authorization) {
    cfg.headers.Authorization = `Bearer ${t}`
  }
  return cfg
})

axios.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      // 2026-07-20 BUG 修: 401 时先清 token (防止后续请求重蹈覆辙)
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      // 公开页 (meta.public=true) 不应该被 401 拦截器跳登录
      // 公开页: /home (公开 landing) + /market (公开市场行情) + /login (本身就在登录页) + / (根路径, 跳 /home)
      // 2026-07-24 BUG 修: 原列表 '/showcase' 已于 7-21 重命名为 '/home'; '/market' 7-23 新增时漏加
      const PUBLIC_PATHS = ['/home', '/market', '/login', '/']
      const isPublicPath = PUBLIC_PATHS.some(p =>
        location.pathname === p || location.pathname.startsWith(p + '/')
      )
      if (!isPublicPath && !location.pathname.startsWith('/login')) {
        const next = encodeURIComponent(location.pathname + location.search)
        location.href = `/login?next=${next}`
      }
    }
    return Promise.reject(err)
  }
)

// ── 兼容旧用法:也导出一个带 baseURL 的实例 ────────────────────
export const api = axios.create({
  baseURL: API,
  timeout: 30000,
})

// 同步拦截器到 instance(如果别的代码用这个 instance)
api.interceptors.request.use((cfg) => {
  // /market 守卫 — 与全局 axios 保持一致
  if (isMarketRoute()) {
    const url = cfg.url || ''
    const isApiCall = url.includes('/api/')
    if (isApiCall && !isMarketAllowed(url)) {
      console.warn(
        `[market-guard] /market 页面拒绝调用 ${url}` +
        '\n  原因:该接口不属于 /market 范畴,防止数据层污染'
      )
      return Promise.reject(new Error(`market-guard blocked (axios instance): ${url}`))
    }
  }
  const t = getToken()
  if (t && !cfg.headers.Authorization) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      // 2026-07-24 BUG 修: 补 /market (公开市场行情页)
      const PUBLIC_PATHS = ['/home', '/market', '/login', '/'] 
      const isPublicPath = PUBLIC_PATHS.some(p =>
        location.pathname === p || location.pathname.startsWith(p + '/')
      )
      if (!isPublicPath && !location.pathname.startsWith('/login')) {
        const next = encodeURIComponent(location.pathname + location.search)
        location.href = `/login?next=${next}`
      }
    }
    return Promise.reject(err)
  }
)

// 监听 useAuth 的 logout 事件(目前 useAuth 自己清,这里只是占位)
window.addEventListener('cjt:auth:logout', () => {})

export { API }
export default axios