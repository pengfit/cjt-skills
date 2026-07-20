<!--
  App.vue (2026-07-19 增加 showcase 公开分支)
  2026-07-20 增强: 加 console.log 诊断, 排查 /showcase 跳 /login 或 /cockpit
-->
<template>
  <!-- 2026-07-20: 对外展示首页(/showcase) — 不受鉴权门控制,访客可直访; 旧 /index 兼容 redirect -->
  <ShowcaseView v-if="route.name === 'showcase'" />
  <NotFoundView v-else-if="route.name === 'not-found'" />
  <LoginView v-else-if="!isAuthed" />
  <DashboardView v-else />
</template>

<script setup>
import { useRoute } from 'vue-router'
import LoginView from './components/LoginView.vue'
import DashboardView from './components/DashboardView.vue'
import ShowcaseView from './components/ShowcaseView.vue'
import NotFoundView from './components/NotFoundView.vue'
import { useAuth } from './composables/useAuth.js'

const route = useRoute()
const { isAuthed } = useAuth()

</script>

<style>
/* 顶层样式由各子组件自带,这里仅放兜底 */
html, body, #app { margin: 0; padding: 0; height: 100%; }
</style>
