<template>
  <header class="top-bar">
    <div class="top-bar-left">
      <button class="mobile-sidebar-btn" @click="$emit('toggle-sidebar')" aria-label="打开侧栏">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
        </svg>
      </button>
      <span class="top-bar-icon" aria-hidden="true">
        <svg width="28" height="28" viewBox="0 0 64 64">
          <defs>
            <linearGradient id="tbBg" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#eff6ff"/>
              <stop offset="100%" stop-color="#dbeafe"/>
            </linearGradient>
            <linearGradient id="tbRing" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#3b82f6"/>
              <stop offset="100%" stop-color="#2563eb"/>
            </linearGradient>
          </defs>
          <rect x="2" y="2" width="60" height="60" rx="14" fill="url(#tbBg)"/>
          <circle cx="32" cy="32" r="24" fill="none" stroke="url(#tbRing)" stroke-width="6" stroke-linecap="round" stroke-dasharray="105 151"/>
        </svg>
      </span>
      <span class="top-bar-brand">材价通</span>
      <span class="top-bar-en">GOV-PRICE</span>
    </div>
    <div class="top-bar-meta">
      <span class="meta-item">
        <span class="meta-label">省份</span>
        <span class="meta-value">{{ overview.total_provinces }}</span>
      </span>
      <span class="meta-sep" aria-hidden="true">|</span>
      <span class="meta-item">
        <span class="meta-label">城市</span>
        <span class="meta-value">{{ overview.total_cities }}</span>
      </span>
      <span class="meta-sep" aria-hidden="true">|</span>
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
defineProps({
  overview: { type: Object, required: true },
})
defineEmits(['toggle-sidebar'])
</script>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: var(--topbar-h);
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
}

.top-bar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mobile-sidebar-btn {
  display: none;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px;
  color: var(--text-2);
  cursor: pointer;
  transition: all 0.15s;
}
.mobile-sidebar-btn:hover {
  background: var(--surface-2);
  color: var(--text);
}

.top-bar-icon {
  display: inline-flex;
  align-items: center;
}

.top-bar-brand {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 1px;
}

.top-bar-en {
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 3px;
  font-family: var(--font-mono-num);
  font-weight: 600;
  padding: 2px 6px;
  border: 1px solid var(--border);
  border-radius: 3px;
}

.top-bar-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 13px;
}

.meta-item {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
}

.meta-label {
  color: var(--text-3);
  font-size: 12px;
}

.meta-value {
  color: var(--text);
  font-weight: 700;
  font-family: var(--font-mono-num);
  font-variant-numeric: tabular-nums;
}

.meta-sep {
  color: var(--border-strong);
}

@media (max-width: 768px) {
  .top-bar-en { display: none; }
  .mobile-sidebar-btn { display: inline-flex; }
  .meta-item:not(:first-child) { display: none; }
  .meta-sep:not(:first-of-type) { display: none; }
}
</style>


/* ⌘K 命令面板入口（fix 2026-07-12） */
.cmd-palette-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 10px;
  background: rgba(255,255,255,0.6);
  border: 1px solid rgba(15,23,42,0.1);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: #64748b;
  transition: all 0.15s;
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
