/**
 * 主题切换 composable (2026-07-12 P2-5)
 *
 * 用法:
 *   const { theme, isDark, toggle } = useTheme()
 *
 * - 初始化:localStorage > 系统偏好(prefers-color-scheme) > light
 * - 切换:写 data-theme 到 <html> + 写 localStorage
 * - 暴露给 ECharts 主题 useEchartsTheme 的 getGovPriceTheme()
 */
import { ref, watch } from 'vue'

const STORAGE_KEY = 'gov-price-theme'

function detectInitial() {
  if (typeof window === 'undefined') return 'light'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'dark' || stored === 'light') return stored
  if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) return 'dark'
  return 'light'
}

// 单例:跨组件共享同一个 theme ref
let _theme = null
let _initialized = false

function applyToDom(theme) {
  if (typeof document === 'undefined') return
  document.documentElement.setAttribute('data-theme', theme)
}

export function useTheme() {
  if (!_initialized) {
    _theme = ref(detectInitial())
    applyToDom(_theme.value)
    _initialized = true
    // 跟随系统偏好(只在用户没显式选过时)
    if (typeof window !== 'undefined' && window.matchMedia) {
      const mq = window.matchMedia('(prefers-color-scheme: dark)')
      mq.addEventListener?.('change', e => {
        if (!window.localStorage.getItem(STORAGE_KEY)) {
          _theme.value = e.matches ? 'dark' : 'light'
        }
      })
    }
    watch(_theme, v => {
      applyToDom(v)
      try { window.localStorage.setItem(STORAGE_KEY, v) } catch {}
    })
  }

  function toggle() {
    _theme.value = _theme.value === 'dark' ? 'light' : 'dark'
  }
  function set(t) {
    if (t === 'dark' || t === 'light') _theme.value = t
  }

  return {
    theme: _theme,
    isDark: () => _theme.value === 'dark',
    toggle,
    set,
  }
}