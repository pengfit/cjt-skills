<!--
  AdminTabPanel.vue — 2026-07-29 重构

  用途: 替换 DashboardView 里 9 个 tab 的 3 种不一致 wrapper 模式
  用法: <AdminTabPanel :loading="tabLoading"><Component /></AdminTabPanel>

  设计:
    - loading=true  → 显示 spinner (admin-loading)
    - loading=false → 直接渲染 slot 内容
    - 不强制包 .admin-page 容器(各 View 自己加)
-->
<template>
  <div class="admin-tab-panel">
    <div v-if="loading" class="admin-loading">
      <div class="admin-loading__spinner"></div>
      <span>{{ loadingText || '加载中...' }}</span>
    </div>
    <slot v-else />
  </div>
</template>

<script setup>
defineProps({
  loading: { type: Boolean, default: false },
  loadingText: { type: String, default: '加载中...' },
})
</script>

<style scoped>
.admin-tab-panel {
  min-height: 100%;
  width: 100%;
}
</style>