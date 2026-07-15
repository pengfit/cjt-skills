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
      <!-- P1-5 KPI 可点击 chip:加右侧 → 暗示 -->
      <button
        class="meta-item meta-item-btn kpi-chip"
        :title="`跳到「全部数据」按 ${overview.total_provinces} 个省份筛选`"
        @click="$emit('go-list', { scope: 'province' })"
      >
        <span class="meta-label">省份</span>
        <span class="meta-value">{{ overview.total_provinces }}</span>
        <span class="kpi-arrow">→</span>
      </button>
      <button
        class="meta-item meta-item-btn kpi-chip"
        :title="`跳到「全部数据」按 ${overview.total_cities} 个城市筛选`"
        @click="$emit('go-list', { scope: 'city' })"
      >
        <span class="meta-label">城市</span>
        <span class="meta-value">{{ overview.total_cities }}</span>
        <span class="kpi-arrow">→</span>
      </button>
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
      <!-- P0-2 立即刷新(统一轮询入口) -->
      <button
        class="refresh-btn"
        @click="$emit('refresh-now')"
        title="立即拉取最新数据(驾驶舱、告警同步刷新)"
      >
        <span class="refresh-icon">↻</span>
      </button>
      <!-- P0-2 暂停/继续轮询 -->
      <button
        class="pause-btn"
        :class="{ paused: pollingPaused }"
        @click="$emit('toggle-polling')"
        :title="pollingPaused ? `轮询已暂停,点击恢复(每 ${pollIntervalMin} 分钟自动刷新)` : `轮询运行中,点击暂停`"
      >
        <span class="pause-icon">{{ pollingPaused ? '▶' : '⏸' }}</span>
      </button>
      <!-- 主题切换（2026-07-12 P2-5）：深浅主题,持久化到 localStorage -->
      <button
        class="theme-toggle"
        @click="toggleTheme"
        :title="isDark ? '切换到浅色主题' : '切换到深色主题'"
        :aria-label="isDark ? '切换到浅色主题' : '切换到深色主题'"
      >
        <span class="theme-icon">{{ isDark ? '☀️' : '🌙' }}</span>
      </button>
      <!-- ⌘K 命令面板入口提示（fix 2026-07-12） -->
      <!-- P1-6 ⌘K trigger:底色提亮 + 按 / 也行 -->
      <button
        class="cmd-palette-trigger"
        @click="$emit('open-cmd-palette')"
        title="搜索页面、命令…（⌘K / Ctrl+K / /）"
      >
        <span class="cmd-icon">🔍</span>
        <span class="cmd-hint">搜索</span>
        <span class="cmd-hint-sep">·</span>
        <span class="cmd-hint-slash">/</span>
        <kbd class="cmd-kbd">⌘K</kbd>
      </button>
    </div>
  </header>
</template>

<script setup>
import { useTheme } from '../../composables/useTheme'
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
 *     @go-list="goList"
 *   />
 */
defineProps({
  overview:         { type: Object, required: true },  // { total_provinces, total_cities, ... }
  alerts:           { type: Object, required: true },  // { count, veryStaleCount, updates }
  lastRefresh:      { type: String, default: '' },       // 接口响应 ISO 时间,用于 tooltip
  lastRefreshAgo:   { type: String, default: '' },       // "更新于 3 分钟前" 等动态文案
  pollingPaused:    { type: Boolean, default: false },  // P0-2 全局轮询暂停状态
  pollIntervalMin:  { type: Number, default: 15 },       // P0-2 轮询周期(分钟)
})

defineEmits(['toggle-sidebar', 'open-cmd-palette', 'go-health', 'go-list', 'toggle-polling', 'refresh-now'])

const { isDark, toggle } = useTheme()
function toggleTheme() {
  toggle()
}
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

/* 顶栏 KPI 可点击变体（fix 2026-07-12 P3-batch1） */
.meta-item-btn {
  border: 1px solid transparent;
  cursor: pointer;
  font-family: inherit;
  color: inherit;
}
.meta-item-btn:hover {
  border-color: var(--primary);
}
/* P1-5 KPI chip:箭头默认隐藏,hover 滑入 */
.kpi-chip {
  position: relative;
  padding-right: 8px;
  transition: all 0.2s ease;
}
.kpi-chip .kpi-arrow {
  font-size: 11px;
  color: var(--primary);
  opacity: 0;
  transform: translateX(-4px);
  transition: all 0.2s ease;
  margin-left: 2px;
}
.kpi-chip:hover {
  background: var(--primary-light);
  border-color: var(--primary);
}
.kpi-chip:hover .kpi-arrow {
  opacity: 1;
  transform: translateX(0);
}
.kpi-chip:active {
  transform: scale(0.96);
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

/* 主题切换按钮 (P2-5) */
.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-round);
  cursor: pointer;
  transition: all 0.18s ease;
  font-family: inherit;
  padding: 0;
}
.theme-toggle:hover {
  background: var(--surface-3);
  border-color: var(--primary);
  transform: rotate(15deg);
}
.theme-icon {
  font-size: 14px;
  line-height: 1;
  display: inline-block;
  transition: transform 0.3s ease;
}
.theme-toggle:hover .theme-icon {
  transform: scale(1.15);
}

/* P0-2 立即刷新按钮(与暂停按钮同体系,简洁圆形) */
.refresh-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-round);
  cursor: pointer;
  transition: all 0.18s ease;
  font-family: inherit;
  padding: 0;
}
.refresh-btn:hover {
  background: var(--primary-light);
  border-color: var(--primary);
  color: var(--primary);
  transform: rotate(-180deg);
}
.refresh-icon {
  font-size: 14px;
  line-height: 1;
  display: inline-block;
}

/* P0-2 暂停/继续轮询按钮 */
.pause-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-round);
  cursor: pointer;
  transition: all 0.18s ease;
  font-family: inherit;
  padding: 0;
  position: relative;
}
.pause-btn:hover {
  border-color: var(--primary);
}
.pause-icon {
  font-size: 12px;
  line-height: 1;
}
.pause-btn.paused {
  background: rgba(234, 88, 12, 0.10);
  border-color: #fdba74;
  color: var(--warning-orange, #ea580c);
}
.pause-btn.paused::after {
  content: '';
  position: absolute;
  top: 4px;
  right: 4px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warning-orange, #ea580c);
  animation: pulse-dot 1.5s ease-in-out infinite;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* P1-6 ⌘K 命令面板入口:存在感提亮 */
.cmd-palette-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 10px;
  background: var(--primary-light);
  border: 1px solid rgba(30,64,175,0.20);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-2);
  transition: all 0.15s;
  font-family: inherit;
  animation: cmd-pulse 3s ease-in-out 1.5s 1;  /* 首屏后 1.5s 一次脉动 */
}
@keyframes cmd-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(30,64,175,0.30); }
  50%      { box-shadow: 0 0 0 6px rgba(30,64,175,0.00); }
}
.cmd-palette-trigger:hover {
  background: var(--surface);
  border-color: var(--primary);
  color: var(--text);
  transform: translateY(-1px);
}
.cmd-hint-sep { color: var(--text-3); opacity: 0.5; font-size: 10px; }
.cmd-hint-slash {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  padding: 0 4px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--text-2);
  font-weight: 600;
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
   A11Y (P2-3): 跳过链接 - 让 Tab 用户第一下跳过整条侧栏
   ============================================================ */
.skip-link {
  position: absolute;
  top: -100px;
  left: 8px;
  z-index: 9999;
  padding: 8px 14px;
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  border-radius: 6px;
  text-decoration: none;
  box-shadow: 0 4px 12px rgba(15,23,42,0.25);
  transition: top 0.15s ease;
}
.skip-link:focus,
.skip-link:focus-visible {
  top: 8px;
  outline: 2px solid #fff;
  outline-offset: 2px;
}
/* main 区域 tabindex=-1 焦点环 (避免粗黑环) */
.main-content:focus,
.main-content:focus-visible {
  outline: none;
}

/* ============================================================
   移动端:meta 整体隐藏(释放空间);断点跟 style.css @media 同步
   ============================================================ */
@media (max-width: 768px) {
  .top-bar-meta { display: none; }
}
</style>