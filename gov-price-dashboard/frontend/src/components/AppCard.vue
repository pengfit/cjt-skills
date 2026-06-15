<template>
  <div
    class="app-card"
    :class="[
      `app-card--${variant}`,
      { 'app-card--hoverable': hoverable, 'app-card--clickable': clickable },
    ]"
    :style="accent ? { '--card-accent': accent } : null"
    @click="clickable && $emit('click', $event)"
  >
    <div v-if="title || $slots.header" class="app-card__header">
      <slot name="header">
        <div class="app-card__title-row">
          <span v-if="dot" class="app-card__dot" :style="dotStyle"></span>
          <span v-if="title" class="app-card__title">{{ title }}</span>
          <span v-if="subtitle" class="app-card__subtitle">{{ subtitle }}</span>
        </div>
      </slot>
      <div v-if="$slots.actions" class="app-card__actions">
        <slot name="actions" />
      </div>
    </div>
    <div class="app-card__body" :class="{ 'app-card__body--padded': padded }">
      <slot />
    </div>
    <div v-if="$slots.footer" class="app-card__footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  /** 顶部 4px 强调色条 */
  accent: { type: String, default: '' },
  /** 标题前的圆点（颜色可用 CSS 变量覆盖） */
  dot: { type: Boolean, default: false },
  dotColor: { type: String, default: '' },
  /** default / outlined / filled */
  variant: { type: String, default: 'default' },
  hoverable: { type: Boolean, default: false },
  clickable: { type: Boolean, default: false },
  /** body 区域是否需要 padding */
  padded: { type: Boolean, default: true },
})

defineEmits(['click'])

const dotStyle = computed(() =>
  props.dotColor ? { background: props.dotColor } : null
)
</script>

<style scoped>
.app-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow);
  overflow: hidden;
  position: relative;
}

.app-card--outlined {
  box-shadow: none;
}

.app-card--filled {
  background: var(--surface-2);
}

.app-card--hoverable {
  transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
}
.app-card--hoverable:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--border-strong);
}

.app-card--clickable {
  cursor: pointer;
}

/* 顶部强调色条 */
.app-card[style*="--card-accent"]::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  background: var(--card-accent);
  pointer-events: none;
}

/* Header */
.app-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-light);
  gap: 12px;
}

.app-card__title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.app-card__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary);
  flex-shrink: 0;
}

.app-card__title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.app-card__subtitle {
  font-size: 12px;
  color: var(--text-3);
  font-weight: 400;
}

.app-card__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* Body */
.app-card__body--padded {
  padding: 16px 18px;
}

/* Footer */
.app-card__footer {
  padding: 12px 18px;
  border-top: 1px solid var(--border-light);
  background: var(--surface-2);
}
</style>
