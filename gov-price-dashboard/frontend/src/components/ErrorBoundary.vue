<template>
  <slot />
</template>

<script setup>
import { onMounted } from 'vue'

const props = defineProps({
  fallback: {
    type: Object,
    default: () => ({
      title: '加载失败',
      icon: '💥',
      hint: '请检查网络连接，或点击下方按钮重试',
    }),
  },
  onRetry: {
    type: Function,
    default: null,
  },
})

const emit = defineEmits(['error'])

// Global error handler — catches all unhandled errors in child components
function globalErrorHandler(err, instance, info) {
  console.error('[ErrorBoundary]', err, info)
  emit('error', { err, info })
  return false // prevent bubbling
}

onMounted(() => {
  window.addEventListener('error', e => {
    console.error('[Global Error]', e.error)
  })
  window.addEventListener('unhandledrejection', e => {
    console.error('[Unhandled Rejection]', e.reason)
  })
})
</script>

<style scoped>
/* No styles needed — pure logic component */
</style>