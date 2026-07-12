<template>
  <div
    class="stat-card"
    :class="[
      `stat-card--${variant}`,
      { 'stat-card--bordered': bordered, 'stat-card--clickable': clickable },
    ]"
    :style="accentStyle"
    @click="clickable && $emit('click', $event)"
  >
    <div class="stat-card-inner">
      <div v-if="icon || $slots.icon" class="stat-icon">
        <slot name="icon">{{ icon }}</slot>
      </div>
      <div class="stat-content">
        <div v-if="label" class="stat-label">{{ label }}</div>
        <div class="stat-value">
          <span class="stat-num">{{ formattedValue }}</span>
          <span v-if="unit" class="stat-unit">{{ unit }}</span>
        </div>
        <div v-if="sub || $slots.sub" class="stat-sub">
          <slot name="sub">{{ sub }}</slot>
        </div>
      </div>
      <div v-if="$slots.extra" class="stat-extra">
        <slot name="extra" />
      </div>
    </div>
    <div v-if="glow" class="stat-glow"></div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'

const props = defineProps({
  label: { type: String, default: '' },
  value: { type: [String, Number], default: '' },
  unit: { type: String, default: '' },
  sub: { type: String, default: '' },
  icon: { type: String, default: '' },
  /** 视觉变体：default | primary | accent（暖橙）| success | danger */
  variant: { type: String, default: 'default' },
  /** 是否带边框（默认无边框，配合大背景使用） */
  bordered: { type: Boolean, default: true },
  /** 是否可点击（hover 效果） */
  clickable: { type: Boolean, default: false },
  /** 是否启用右侧 glow 高光（用于突出主指标） */
  glow: { type: Boolean, default: false },
  /** 自定义顶部 4px 强调色（覆盖 variant） */
  accent: { type: String, default: '' },
  /** 数值格式化：auto | raw */
  format: { type: String, default: 'auto' },
})

defineEmits(['click'])

const accentStyle = computed(() => (props.accent ? { '--stat-accent': props.accent } : null))

const fmt = useFormatNumber()
const formattedValue = computed(() => {
  if (typeof props.value === 'number' && props.format === 'auto') {
    return fmt.int(props.value)
  }
  return props.value
})
</script>

<style scoped>
.stat-card {
  position: relative;
  background: var(--surface);
  border-radius: 12px;
  transition: all 0.18s ease;
  overflow: hidden;
  display: flex;
}

.stat-card--bordered {
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}

.stat-card--clickable {
  cursor: pointer;
}
.stat-card--clickable:hover {
  border-color: var(--primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.stat-card[style*="--stat-accent"]::before {
  content: '';
  position: absolute;
  top: 0; left: 0;
  width: 100%;
  height: 3px;
  background: var(--stat-accent);
}

.stat-card-inner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  width: 100%;
  min-width: 0;
}

.stat-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--primary-dim);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.stat-card--success .stat-icon { background: var(--status-ok-bg); color: var(--status-ok); }
.stat-card--danger  .stat-icon { background: var(--status-alert-bg); color: var(--status-alert); }
.stat-card--accent  .stat-icon { background: rgba(234,88,12,0.10); color: var(--warning-orange, #ea580c); }

.stat-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-label {
  font-size: 12px;
  color: var(--text-2);
  font-weight: 500;
  letter-spacing: 0.2px;
}

.stat-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
  line-height: 1.2;
}

.stat-num {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  font-family: var(--font-mono-num);
  letter-spacing: -0.01em;
}
.stat-card--primary .stat-num { color: var(--primary); }
.stat-card--success .stat-num { color: var(--status-ok); }
.stat-card--danger  .stat-num { color: var(--status-alert); }
.stat-card--accent  .stat-num { color: var(--warning-orange, #ea580c); }

.stat-unit {
  font-size: 12px;
  color: var(--text-3);
  font-weight: 500;
}

.stat-sub {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 2px;
}

.stat-extra {
  flex-shrink: 0;
}

/* Glow（仅在 accent 模式下渲染） */
.stat-glow {
  position: absolute;
  top: -40px;
  right: -40px;
  width: 120px;
  height: 120px;
  background: radial-gradient(circle, rgba(234,88,12,0.10) 0%, transparent 70%);
  border-radius: 50%;
  pointer-events: none;
}

/* 紧凑变体（用在 row 内联场景） */
:slotted(.stat-num-compact) { font-size: 16px; }
</style>