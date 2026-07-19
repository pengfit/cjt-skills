/** 鉴权状态(2026-07-19)
 *
 * 单 admin 登录,JWT 存 localStorage。
 * useApi.js 的 axios 拦截器会读这里。
 */
import { ref, computed } from 'vue'

const TOKEN_KEY = 'cjt_jwt'
const USER_KEY = 'cjt_user'

const token = ref(localStorage.getItem(TOKEN_KEY) || '')
const user = ref(JSON.parse(localStorage.getItem(USER_KEY) || 'null'))

const isAuthed = computed(() => !!token.value)

async function login(username, password) {
  // OAuth2 Password Flow: application/x-www-form-urlencoded
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
  // 通知 axios 拦截器清状态（如果它在别处订阅了）
  window.dispatchEvent(new CustomEvent('cjt:auth:logout'))
}

export function getToken() {
  return token.value
}

export function useAuth() {
  return { token, user, isAuthed, login, logout }
}