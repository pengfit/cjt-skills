<template>
  <header class="top-bar">
    <div class="top-bar-left">
      <button class="hamburger" @click="$emit('toggle-sidebar')" aria-label="菜单">
        <span></span><span></span><span></span>
      </button>
      <span class="brand-logo">价</span>
      <span class="top-bar-title">材价通</span>
    </div>
    <div class="top-bar-meta">
      <span class="meta-item">
        <span class="meta-label">省份</span>
        <span class="meta-value">{{ overview.total_provinces }}</span>
      </span>
      <span class="meta-item">
        <span class="meta-label">城市</span>
        <span class="meta-value">{{ overview.total_cities }}</span>
      </span>
      <!-- 数据新鲜度告警（fix 2026-07-12 P1-4）：stale/very_stale 城市数,点击跳数据健康 -->
      <button
        v-if="alerts.count > 0"
        class="alert-badge"
        :class="{ severe: alerts.veryStaleCount > 0 }"
        @click="$emit('go-health')"
        :title="`${alerts.count} 城数据待更新,点击查看`"
      >
        <span class="alert-icon">⚠</span>
        <span class="alert-count">{{ alerts.count }}</span>
      </button>
      <span v-else class="alert-ok" title="全部 18 城数据新鲜">
        <span class="alert-ok-dot">●</span>
        <span class="alert-ok-text">全部新鲜</span>
      </span>
      <!-- 最后刷新时间(同上):每分钟重算"X 分钟前" -->
      <span v-if="lastRefreshAgo" class="last-refresh" :title="`接口扫描: ${lastRefresh}`">
        {{ lastRefreshAgo }}
      </span>
      <!-- ⌘K 命令面板入口提示（fix 2026-07-12） -->
      <button
        class="cmd-palette-trigger"
        @click="$emit('open-cmd-palette')"
        title="搜索页面、命令…（⌘K / Ctrl+K）"
      >
        <span class="cmd-icon">🔍</span>
        <span class="cmd-hint">搜索</span>
        <kbd class="cmd-kbd">⌘K</kbd>
      </button>
    </div>
  </header>
</template>

<script setup>
/**
 * 顶栏(统一组件)
 * 由父级传入数据(overview / alerts / lastRefresh / lastRefreshAgo),
 * 内部只负责渲染 + 触发交互(emit),数据拉取/定时器在父级。
 *
 * @example
 *   <TopBar
 *     :overview="overview"
 *     :alerts="alerts"
 *     :last-refresh="lastRefresh"
 *     :last-refresh-ago="lastRefreshAgo"
 *     @toggle-sidebar="mobileSidebarOpen = !mobileSidebarOpen"
 *     @open-cmd-palette="showCmdPalette = true"
 *     @go-health="goHealth"
 *   />
 */
defineProps({
  overview:         { type: Object, required: true },  // { total_provinces, total_cities, ... }
  alerts:           { type: Object, required: true },  // { count, veryStaleCount, updates }
  lastRefresh:      { type: String, default: '' },       // 接口响应 ISO 时间,用于 tooltip
  lastRefreshAgo:   { type: String, default: '' },       // "更新于 3 分钟前" 等动态文案
})

defineEmits(['toggle-sidebar', 'open-cmd-palette', 'go-health'])
</script>

<style>
/* ── 注:用 <style> 不带 scoped,因为 style.css 里的 @media (max-width: 768px)
       等响应式规则仍要命中这里的 .top-bar / .top-bar-meta ── */

/* ============================================================
   TOP BAR — 更干净的顶部栏
   ============================================================ */
.top-bar {
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: var(--surface);
  height: var(--topbar-h, 56px);
  margin-bottom: 0;
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
}

.top-bar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 0 0 auto;
}

/* 品牌 logo 圆点 */
.brand-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, #1e40af 0%, #7c3aed 100%);
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  flex-shrink: 0;
  letter-spacing: 0;
  box-shadow: 0 2px 8px rgba(30,64,175,0.3);
}

.top-bar-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 0.5px;
}

/* ——— Hamburger(移动端菜单触发) ——— */
.hamburger {
  display: none;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  width: 28px;
  height: 28px;
  padding: 4px;
  border: none;
  background: transparent;
  cursor: pointer;
  flex-shrink: 0;
  border-radius: 4px;
  transition: background var(--transition-fast);
}
.hamburger:hover { background: rgba(var(--primary-rgb), 0.06); }
.hamburger span {
  display: block;
  width: 100%;
  height: 2px;
  background: var(--text-2);
  border-radius: 1px;
  transition: all var(--transition-fast);
}
@media (max-width: 768px) {
  .hamburger { display: flex; }
  /* 打开移动侧栏后,隐藏品牌 + 标题,只留汉堡 */
  .dashboard.mobile-sidebar-open .brand-logo,
  .dashboard.mobile-sidebar-open .top-bar-title { display: none; }
}

.top-bar-divider {
  width: 1px;
  height: 22px;
  background: var(--border);
  flex-shrink: 0;
}

.top-bar-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-2);
  flex: 0 0 auto;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: var(--radius-round);
  background: var(--surface-2);
  transition: background var(--transition-fast);
}
.meta-item:hover {
  background: rgba(var(--primary-rgb), 0.08);
}

.meta-label {
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
}

.meta-value {
  font-weight: 700;
  font-family: var(--font-mono-num);
  color: var(--primary);
  font-size: 13px;
  letter-spacing: 0.2px;
  transition: all 0.3s ease;
}

/* ============================================================
   P1-4: 数据新鲜度告警 + 刷新时间 + ⌘K 入口
   ============================================================ */

/* 告警徽章:橙色(普通 stale) / 红色(very_stale) */
.alert-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px 2px 6px;
  background: #fff7ed;
  border: 1px solid #fdba74;
  border-radius: var(--radius-round);
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  color: #c2410c;
  transition: all 0.15s;
  font-family: inherit;
}
.alert-badge:hover {
  background: #ffedd5;
  border-color: #f97316;
}
.alert-badge.severe {
  background: #fef2f2;
  border-color: #fca5a5;
  color: #b91c1c;
}
.alert-badge.severe:hover {
  background: #fee2e2;
  border-color: #ef4444;
}
.alert-icon { font-size: 12px; line-height: 1; }
.alert-count {
  font-family: var(--font-mono-num);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  font-weight: 700;
}

/* 全部新鲜绿点 */
.alert-ok {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: var(--radius-round);
  font-size: 11px;
  font-weight: 500;
  color: #15803d;
}
.alert-ok-dot {
  color: #22c55e;
  font-size: 10px;
  line-height: 1;
  animation: alert-ok-pulse 2.5s ease-in-out infinite;
}
@keyframes alert-ok-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.alert-ok-text { font-size: 11px; }

/* "更新于 X 分钟前" */
.last-refresh {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  background: var(--surface-2);
  border-radius: var(--radius-round);
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono-num);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* ⌘K 命令面板入口 */
.cmd-palette-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 10px;
  background: rgba(255,255,255,0.7);
  border: 1px solid rgba(15,23,42,0.1);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: #64748b;
  transition: all 0.15s;
  font-family: inherit;
}
.cmd-palette-trigger:hover {
  background: white;
  border-color: rgba(37, 99, 235, 0.3);
}
.cmd-icon { font-size: 12px; }
.cmd-hint { font-size: 12px; }
.cmd-kbd {
  font-family: ui-monospace, monospace;
  font-size: 10px;
  padding: 1px 5px;
  background: rgba(15,23,42,0.06);
  border: 1px solid rgba(15,23,42,0.1);
  border-radius: 3px;
  color: #475569;
}

/* ============================================================
   移动端:meta 整体隐藏(释放空间);断点跟 style.css @media 同步
   ============================================================ */
@media (max-width: 768px) {
  .top-bar-meta { display: none; }
}
</style>