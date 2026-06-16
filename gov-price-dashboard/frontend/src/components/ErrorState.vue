<template>
  <div class="error-state" :class="{ compact }">
    <div class="error-icon">{{ icon || '⚠️' }}</div>
    <div v-if="title" class="error-title">{{ title }}</div>
    <div v-if="message" class="error-message">{{ message }}</div>
    <div v-if="detail" class="error-detail">{{ detail }}</div>
    <div v-if="$slots.default || onRetry" class="error-actions">
      <button v-if="onRetry" class="btn-retry" @click="onRetry">
        <span aria-hidden="true">🔄</span>
        <span>重试</span>
      </button>
      <slot />
    </div>
  </div>
</template>

<script setup>
defineProps({
  icon: { type: String, default: '' },
  title: { type: String, default: '加载失败' },
  message: { type: String, default: '请检查网络或数据服务' },
  detail: { type: String, default: '' },
  compact: { type: Boolean, default: false },
  onRetry: { type: Function, default: null },
})
</script>

<style scoped>
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text-2);
  text-align: center;
  gap: 8px;
}
.error-state.compact { padding: 24px 16px; }

.error-icon {
  font-size: 42px;
  opacity: 0.65;
  margin-bottom: 6px;
}
.compact .error-icon { font-size: 28px; }

.error-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--danger);
}
.error-message {
  font-size: 13px;
  color: var(--text-2);
  max-width: 360px;
  line-height: 1.5;
}
.error-detail {
  font-size: 11px;
  color: var(--text-3);
  max-width: 480px;
  line-height: 1.5;
  font-family: var(--font-mono-num);
  background: var(--surface-2);
  padding: 6px 10px;
  border-radius: 4px;
  margin-top: 4px;
  word-break: break-all;
}
.error-actions {
  margin-top: 14px;
  display: flex;
  gap: 8px;
}
.btn-retry {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--primary);
  color: var(--text-inverse);
  border: none;
  padding: 7px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-retry:hover {
  background: var(--primary-dark);
  box-shadow: var(--shadow-primary);
}
.btn-retry:active {
  transform: translateY(1px);
}
</style>
