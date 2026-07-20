<!--
  ShowcaseNav.vue - 顶部极简 nav
  公开访客用,只放 logo(2026-07-19 删除"进入 Dashboard"入口,道友要求)
  2026-07-20: OPC 文字 mark 替换成 OPC Icon (修改 9)
-->
<template>
  <nav class="s-nav">
    <div class="s-nav-inner">
      <router-link to="/showcase" class="s-brand">
        <svg class="opc-icon" viewBox="0 0 32 32" width="22" height="22" aria-label="Pengfit" role="img">
          <!-- 外圈: 公司边界 -->
          <circle cx="16" cy="16" r="14.5" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.55" stroke-dasharray="2 2"/>
          <!-- 中央 1 人 (头 + 肩) -->
          <circle cx="16" cy="12" r="3" fill="currentColor"/>
          <path d="M 10 22 Q 10 17 16 17 Q 22 17 22 22 Z" fill="currentColor"/>
          <!-- 周围 3 个 AI 节点 + 连接线 -->
          <line x1="13" y1="13.5" x2="7.5" y2="9" stroke="currentColor" stroke-width="1" opacity="0.5"/>
          <line x1="19" y1="13.5" x2="24.5" y2="9" stroke="currentColor" stroke-width="1" opacity="0.5"/>
          <line x1="16" y1="19" x2="16" y2="26" stroke="currentColor" stroke-width="1" opacity="0.5"/>
          <circle cx="6.5" cy="8.5" r="2" fill="currentColor"/>
          <circle cx="25.5" cy="8.5" r="2" fill="currentColor"/>
          <circle cx="16" cy="27.5" r="2" fill="currentColor"/>
        </svg>
        <span class="s-brand-text">Pengfit</span>
      </router-link>
      <span class="s-case-chip">案例 · 材价通</span>

      <!-- 2026-07-20: 暗色模式手动切换按钮 (sun/moon) -->
      <button
        class="s-theme-toggle"
        :class="{ 'is-dark': theme === 'dark' }"
        :title="theme === 'dark' ? '切换到亮色' : '切换到暗色'"
        :aria-label="theme === 'dark' ? '切换到亮色' : '切换到暗色'"
        @click="toggleTheme"
      >
        <!-- sun icon (亮色时显示, 点击切到暗色) -->
        <svg v-if="theme === 'light'" class="theme-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="4"/>
          <line x1="12" y1="2" x2="12" y2="4"/>
          <line x1="12" y1="20" x2="12" y2="22"/>
          <line x1="4.93" y1="4.93" x2="6.34" y2="6.34"/>
          <line x1="17.66" y1="17.66" x2="19.07" y2="19.07"/>
          <line x1="2" y1="12" x2="4" y2="12"/>
          <line x1="20" y1="12" x2="22" y2="12"/>
          <line x1="4.93" y1="19.07" x2="6.34" y2="17.66"/>
          <line x1="17.66" y1="6.34" x2="19.07" y2="4.93"/>
        </svg>
        <!-- moon icon (暗色时显示, 点击切到亮色) -->
        <svg v-else class="theme-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
      </button>
    </div>
  </nav>
</template>

<script setup>
import { ref, onMounted } from 'vue'

// 2026-07-20 暗色模式管理
// 优先级: 1) localStorage 用户选择 2) 系统 prefers-color-scheme 3) 亮色默认
const theme = ref('light')
const THEME_KEY = 'pengfit_theme'

function applyTheme(t) {
  document.documentElement.dataset.theme = t
  theme.value = t
}

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
  try { localStorage.setItem(THEME_KEY, theme.value) } catch { /* ignore */ }
}

onMounted(() => {
  let saved = ''
  try { saved = localStorage.getItem(THEME_KEY) || '' } catch { /* ignore */ }
  if (saved === 'dark' || saved === 'light') {
    applyTheme(saved)
  } else {
    // 跟系统偏好
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    applyTheme(prefersDark ? 'dark' : 'light')
  }
})
</script>

<style scoped>
.s-nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(248, 250, 252, 0.85);
  backdrop-filter: saturate(180%) blur(12px);
  -webkit-backdrop-filter: saturate(180%) blur(12px);
  border-bottom: 1px solid var(--border-light);
}

.s-nav-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 32px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.s-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  color: var(--text);
}

/* OPC Icon (修改 9) */
.opc-icon {
  color: var(--primary);
  flex-shrink: 0;
  display: block;
}

.s-brand-text {
  font-size: 14px;
  color: var(--text-2);
}

.s-case-chip {
  font-size: 11px;
  color: var(--text-3);
  padding: 4px 10px;
  background: var(--surface-2);
  border: 1px solid var(--border-light);
  border-radius: 999px;
  letter-spacing: 0.02em;
}

.s-cta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 500;
  color: var(--primary);
  text-decoration: none;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  transition: all var(--transition);
}

.s-cta:hover {
  background: var(--primary);
  color: var(--text-inverse);
  border-color: var(--primary);
}

.s-cta .arrow {
  transition: transform var(--transition);
}

.s-cta:hover .arrow {
  transform: translateX(2px);
}

@media (max-width: 640px) {
  .s-brand-text { display: none; }
  .s-nav-inner { padding: 0 20px; }
}

/* 2026-07-20 暗色模式切换按钮 */
.s-theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin-left: 12px;
  padding: 0;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-2);
  cursor: pointer;
  transition: all 0.2s ease;
}
.s-theme-toggle:hover {
  background: var(--surface-2);
  color: var(--primary);
  border-color: var(--primary);
}
.s-theme-toggle:active {
  transform: scale(0.92);
}
.s-theme-toggle.is-dark {
  color: var(--primary);
  background: var(--primary-dim);
  border-color: var(--primary);
}
.theme-icon {
  display: block;
  flex-shrink: 0;
}
</style>
