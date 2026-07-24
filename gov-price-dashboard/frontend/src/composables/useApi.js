/** axios 拦截器(2026-07-19) — 装在全局 axios 上,所有用 axios 的地方都生效
 *
 * - request:  自动加 Authorization: Bearer <jwt>
 * - response: 401 时清 token + 跳 /login?next=...
 *
 * 注意:必须 import 这个文件才能注册拦截器。main.js 已 import。
 */
import axios from 'axios'
import { getToken } from './useAuth.js'

const API = import.meta.env.VITE_API_URL || '/api'
const TOKEN_KEY = '***'
const USER_KEY = '***'

// ── 拦截器(全局 axios)────────────────────────────────────────
axios.interceptors.request.use((cfg) => {
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