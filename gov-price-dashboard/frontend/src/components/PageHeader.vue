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