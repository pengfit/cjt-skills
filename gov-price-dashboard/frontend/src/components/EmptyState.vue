<template>
  <div class="empty-state" :class="{ compact }">
    <div class="empty-icon">{{ icon || '📭' }}</div>
    <div v-if="title" class="empty-title">{{ title }}</div>
    <div v-if="message" class="empty-message">{{ message }}</div>
    <div v-if="$slots.default" class="empty-actions">
      <slot />
    </div>
  </div>
</template>

<script setup>
defineProps({
  icon: { type: String, default: '' },
  title: { type: String, default: '暂无数据' },
  message: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text-3);
  text-align: center;
  gap: 8px;
}
.empty-state.compact { padding: 24px 16px; }

.empty-icon {
  font-size: 42px;
  opacity: 0.45;
  margin-bottom: 6px;
  filter: grayscale(0.4);
}
.compact .empty-icon { font-size: 28px; }

.empty-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-3);
}
.empty-message {
  font-size: 12px;
  color: var(--text-3);
  max-width: 320px;
  line-height: 1.5;
}
.empty-actions {
  margin-top: 14px;
  display: flex;
  gap: 8px;
}
</style>
