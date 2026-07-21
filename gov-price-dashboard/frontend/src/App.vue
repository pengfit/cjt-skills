<!--
  App.vue (2026-07-19 增加 showcase 公开分支)
  2026-07-21 改造: /showcase 重命名为 /home,组件 ShowcaseView → HomeView
-->
<template>
  <!-- 2026-07-21: 对外展示首页(/home) — 不受鉴权门控制,访客可直访; 旧 /index 兼容 redirect -->
  <HomeView v-if="route.name === 'home'" />
  <NotFoundView v-else-if="route.name === 'not-found'" />
  <LoginView v-else-if="!isAuthed" />
  <DashboardView v-else />
</template>

<script setup>
import { useRoute } from 'vue-router'
import LoginView from './components/LoginView.vue'
import DashboardView from './components/DashboardView.vue'
import HomeView from './components/HomeView.vue'
import NotFoundView from './components/NotFoundView.vue'
import { useAuth } from './composables/useAuth.js'

const route = useRoute()
const { isAuthed } = useAuth()

</script>

<style>
/* 顶层样式由各子组件自带,这里仅放兜底 */
html, body, #app { margin: 0; padding: 0; height: 100%; }
</style>
