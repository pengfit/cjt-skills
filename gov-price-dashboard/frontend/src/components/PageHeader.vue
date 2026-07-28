<template>
  <header class="page-header" :class="`page-header--${variant}`">
    <div class="page-header-main">
      <h1 v-if="title" class="page-header-title">
        <span v-if="$slots.icon" class="page-header-icon">
          <slot name="icon" />
        </span>
        {{ title }}
      </h1>
      <p v-if="subtitle" class="page-header-subtitle" v-html="subtitle"></p>
      <slot name="below" />
    </div>
    <div v-if="$slots.right || stats?.length || badge" class="page-header-right">
      <slot name="right">
        <div v-if="stats?.length" class="page-header-stats">
          <div
            v-for="(s, i) in stats"
            :key="i"
            class="page-header-stat"
            :title="s.title || ''"
          >
            <span class="page-header-stat-val" :class="s.tone ? `page-header-stat-val--${s.tone}` : ''">
              {{ s.value }}
            </span>
            <span class="page-header-stat-key" v-html="s.label"></span>
          </div>
        </div>
        <span v-else-if="badge" class="page-header-badge">{{ badge }}</span>
      </slot>
    </div>
  </header>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  /** 视觉变体：card（白底+边框+阴影）/ flat（透明+下边框） */
  variant: { type: String, default: 'card' },
  /** 显示在右侧的统计项，例如 [{label:'规则总数', value:'4068', tone:'primary|ok|warn|alert'}] */
  stats: { type: Array, default: null },
  /** 显示在右侧的徽标，与 stats 二选一 */
  badge: { type: String, default: '' },
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
}

/* 2026-07-25 P0-fix: 移动端 wrap + stats 横滚 */
@media (max-width: 768px) {
  .page-header {
    flex-direction: column !important;
    align-items: stretch !important;
    gap: 10px !important;
    padding: 12px !important;
  }
  .page-header-main { min-width: 0; }
  .page-header-title { font-size: 1.05rem !important; line-height: 1.3 !important; word-break: break-word; }
  .page-header-subtitle { font-size: 12px !important; }
  .page-header-right { width: 100% !important; }
  .page-header-stats {
    display: flex !important;
    flex-wrap: nowrap !important;
    overflow-x: auto !important;
    gap: 14px !important;
    padding-bottom: 4px;
    -webkit-overflow-scrolling: touch;
  }
  .page-header-stat { flex: 0 0 auto !important; min-width: 90px !important; }
  .page-header-stat-val { font-size: 18px !important; }
  .page-header-stat-key { font-size: 11px !important; }
  .page-header-badge { font-size: 12px !important; padding: 4px 10px !important; }
}

/* card 变体：白底 + 边框 + 阴影 */
.page-header--card {
  padding: 18px 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow);
}

/* flat 变体：透明 + 下边框（与多个 list/detail 页保持一致） */
.page-header--flat {
  padding: 22px 0 16px;
  border-bottom: 1px solid var(--border);
  align-items: center;
}

.page-header-main { flex: 1; min-width: 0; }

.page-header-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  line-height: 1.4;
  letter-spacing: -0.01em;
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-header-icon {
  font-size: 18px;
  line-height: 1;
}

.page-header-subtitle {
  font-size: 12px;
  color: var(--text-3);
  margin: 4px 0 0 0;
  line-height: 1.6;
}

.page-header-subtitle :deep(strong) {
  color: var(--text);
  font-weight: 600;
}

/* 13" 视口：<code> 长路径(如 skills/data/...db)默认不换行,会撑爆右侧;
   加 overflow-wrap 让长串在必要处可断 */
.page-header-subtitle :deep(code) {
  overflow-wrap: break-word;
  word-break: break-all;
}

.page-header-right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

.page-header-stats {
  display: flex;
  gap: 20px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

/* 13" 视口（1101-1400px）：右侧 stat 在与 main 冲突时允许收缩,避免挤压左侧子标题 */
@media (max-width: 1400px) and (min-width: 769px) {
  .page-header { gap: 16px; }
  .page-header-stats { gap: 14px; }
  .page-header-stat-val { font-size: 16px; }
  .page-header-stat-key { font-size: 10px; }
}

.page-header-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.page-header-stat-val {
  font-size: 18px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono-num);
  line-height: 1.2;
}
.page-header-stat-val--ok    { color: var(--status-ok); }
.page-header-stat-val--warn  { color: var(--status-warn, #ea580c); }
.page-header-stat-val--alert { color: var(--status-alert); }

.page-header-stat-key {
  font-size: 11px;
  color: var(--text-3);
}

.page-header-badge {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
  background: var(--primary-dim);
  border-radius: 999px;
}
</style>