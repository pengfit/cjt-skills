<template>
  <div class="section-header" :class="{ 'with-divider': divider }">
    <div class="section-header-left">
      <span
        v-if="dot"
        class="section-dot"
        :class="dotClass"
        :style="dotStyle"
      ></span>
      <span class="section-title">{{ title }}</span>
      <span v-if="subtitle" class="section-subtitle">{{ subtitle }}</span>
    </div>
    <div v-if="$slots.right" class="section-header-right">
      <slot name="right" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  /** 是否显示左侧圆点 */
  dot: { type: Boolean, default: true },
  /** 圆点颜色：blue | green | purple | amber | red | cyan，默认为 blue */
  dotColor: { type: String, default: 'blue' },
  /** 自定义圆点颜色（覆盖 dotColor） */
  color: { type: String, default: '' },
  /** 是否在下方加一道分隔线 */
  divider: { type: Boolean, default: false },
})

const dotClass = computed(() => `section-dot--${props.dotColor}`)
const dotStyle = computed(() => (props.color ? { background: props.color } : null))
</script>

<style scoped>
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 0;
}

.section-header.with-divider {
  padding: 0 0 12px 0;
  border-bottom: 1px solid var(--border-light);
  margin-bottom: 14px;
}

.section-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.section-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  display: inline-block;
}

.section-dot--blue   { background: var(--primary); box-shadow: 0 0 8px rgba(37,99,235,0.45); }
.section-dot--green  { background: var(--success); box-shadow: 0 0 8px rgba(22,163,74,0.45); }
.section-dot--purple { background: var(--purple); box-shadow: 0 0 8px rgba(124,58,237,0.45); }
.section-dot--amber  { background: var(--warning); box-shadow: 0 0 8px rgba(217,119,6,0.45); }
.section-dot--red    { background: var(--danger); box-shadow: 0 0 8px rgba(220,38,38,0.45); }
.section-dot--cyan   { background: var(--primary); box-shadow: 0 0 8px rgba(37,99,235,0.45); }

.section-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 0.2px;
}

.section-subtitle {
  font-size: 12px;
  color: var(--text-3);
  font-weight: 400;
  margin-left: 4px;
}

.section-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
</style>