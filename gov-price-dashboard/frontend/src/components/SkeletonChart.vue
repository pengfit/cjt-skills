<template>
  <div class="skeleton-chart" :style="{ height: heightStr, borderRadius: radiusStr }">
    <div class="skeleton-grid">
      <div v-for="i in gridLines" :key="'h' + i" class="skeleton-hline" />
      <div v-for="i in yLabels" :key="'y' + i" class="skeleton-y-label" :style="{ top: ((i - 1) * 100 / (yLabels - 1)) + '%' }" />
    </div>
    <div class="skeleton-bars" v-if="variant === 'bar'">
      <div v-for="i in bars" :key="'b' + i" class="skeleton-bar" :style="{ height: (30 + Math.random() * 60) + '%' }" />
    </div>
    <div class="skeleton-line" v-else-if="variant === 'line'">
      <svg viewBox="0 0 100 30" preserveAspectRatio="none" class="skeleton-line-svg">
        <polyline
          points="0,25 8,18 16,22 24,15 32,20 40,12 48,17 56,10 64,14 72,8 80,11 88,5 96,9 100,7"
          fill="none" stroke="currentColor" stroke-width="0.6" stroke-linecap="round"
        />
      </svg>
    </div>
    <div v-else class="skeleton-pulse" />
    <div v-if="showCaption" class="skeleton-caption">{{ caption }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  height: { type: [String, Number], default: 200 },
  radius: { type: [String, Number], default: 8 },
  variant: { type: String, default: 'auto' },  // bar | line | auto
  gridLines: { type: Number, default: 4 },
  yLabels: { type: Number, default: 4 },
  bars: { type: Number, default: 8 },
  showCaption: { type: Boolean, default: false },
  caption: { type: String, default: '加载中…' },
})

const heightStr = computed(() => typeof props.height === 'number' ? props.height + 'px' : props.height)
const radiusStr = computed(() => typeof props.radius === 'number' ? props.radius + 'px' : props.radius)
</script>

<style scoped>
.skeleton-chart {
  background: var(--surface);
  border: 1px solid var(--border);
  position: relative;
  overflow: hidden;
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}
.skeleton-grid {
  position: absolute;
  inset: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  pointer-events: none;
}
.skeleton-hline {
  height: 1px;
  background: var(--border);
  opacity: 0.5;
}
.skeleton-y-label {
  position: absolute;
  right: 0;
  font-size: 10px;
  color: var(--text-3);
  font-family: var(--font-mono-num);
  transform: translateY(-50%);
  background: var(--surface);
  padding: 0 2px;
}

.skeleton-bars {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  height: 100%;
  z-index: 1;
}
.skeleton-bar {
  flex: 1;
  background: linear-gradient(180deg, var(--surface-2) 0%, var(--border) 100%);
  border-radius: 3px 3px 0 0;
  animation: skel-pulse 1.4s ease-in-out infinite;
  min-height: 8px;
}

.skeleton-line {
  height: 100%;
  display: flex;
  align-items: center;
  color: var(--border-strong);
}
.skeleton-line-svg {
  width: 100%;
  height: 60%;
  animation: skel-fade 1.4s ease-in-out infinite;
}

.skeleton-pulse {
  flex: 1;
  background: linear-gradient(
    90deg,
    var(--surface-2) 0%,
    var(--border) 50%,
    var(--surface-2) 100%
  );
  background-size: 200% 100%;
  animation: skel-shimmer 1.4s linear infinite;
  border-radius: 4px;
}

.skeleton-caption {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-3);
  font-size: 12px;
  letter-spacing: 0.5px;
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(0.5px);
}

@keyframes skel-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
@keyframes skel-fade {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.9; }
}
@keyframes skel-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
