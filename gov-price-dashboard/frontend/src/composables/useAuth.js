/** 鉴权状态 (2026-07-19)
 *
 * 单 admin 登录, JWT 存 localStorage。
 * useApi.js 的 axios 拦截器会读这里。
 *
 * 2026-07-20 增强 (道友 BUG: 过期 JWT 让 SPA 误判 isAuthed=true):
 * - 启动时检查 JWT 是否过期 (解析 exp 字段)
 * - 过期自动清理 localStorage + token ref + 触发 auth:logout 事件
 */
import { ref, computed } from 'vue'

const TOKEN_KEY = 'cjt_jwt'
const USER_KEY = 'cjt_user'

/** 解析 JWT payload 的 exp 字段 (base64url) */
function parseJwtExp(tokenStr) {
  if (!tokenStr || typeof tokenStr !== 'string') return null
  const parts = tokenStr.split('.')
  if (parts.length !== 3) return null
  try {
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = payload + '==='.slice(0, (4 - payload.length % 4) % 4)
    const decoded = JSON.parse(atob(padded))
    return typeof decoded.exp === 'number' ? decoded.exp : null
  } catch {
    return null
  }
}

function isJwtExpired(tokenStr) {
  const exp = parseJwtExp(tokenStr)
  if (!exp) return false  // 没 exp 字段就不强行清
  return Math.floor(Date.now() / 1000) >= exp - 30  // 提前 30s 算过期
}

const initialToken = localStorage.getItem(TOKEN_KEY) || ''

// 启动时检查过期, 过期则清理
if (initialToken && isJwtExpired(initialToken)) {
  console.warn('[useAuth] JWT expired at exp, clearing localStorage')
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  window.dispatchEvent(new CustomEvent('cjt:auth:logout'))
}

const token = ref(isJwtExpired(initialToken) ? '' : initialToken)
const user = ref(
  isJwtExpired(initialToken) ? null : JSON.parse(localStorage.getItem(USER_KEY) || 'null')
)

const isAuthed = computed(() => !!token.value)

async function login(username, password) {
  const body = new URLSearchParams({ username, password })
  const r = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: '登录失败' }))
    throw new Error(err.detail || `HTTP ${r.status}`)
  }
  const data = await r.json()
  token.value = data.access_token
  user.value = { username: data.username || username, role: data.role || 'admin' }
  localStorage.setItem(TOKEN_KEY, data.access_token)
  localStorage.setItem(USER_KEY, JSON.stringify(user.value))
  return user.value
}

function logout() {
  token.value = ''
  user.value = null
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  window.dispatchEvent(new CustomEvent('cjt:auth:logout'))
}

export function getToken() {
  return token.value
}

export function getJwtExp(tokenStr) {
  return parseJwtExp(tokenStr)
}

export function useAuth() {
  return { token, user, isAuthed, login, logout }
}
