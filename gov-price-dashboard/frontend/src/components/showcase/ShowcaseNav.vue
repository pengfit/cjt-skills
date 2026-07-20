<!--
  ShowcaseNav.vue - 顶部极简 nav
  公开访客用,只放 logo(2026-07-19 删除"进入 Dashboard"入口,道友要求)
  2026-07-20: OPC 文字 mark 替换成 OPC Icon (修改 9)
-->
<template>
  <nav class="s-nav">
    <div class="s-nav-inner">
      <router-link to="/index" class="s-brand">
        <svg class="opc-icon" viewBox="0 0 32 32" width="22" height="22" aria-label="OPC · One Person Company" role="img">
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
        <span class="s-brand-text">One Person Company</span>
      </router-link>
      <span class="s-case-chip">案例 · 材价通平台</span>
    </div>
  </nav>
</template>

<script setup>
// 无状态
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
</style>
