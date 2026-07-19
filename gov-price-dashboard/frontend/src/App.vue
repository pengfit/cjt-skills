<!--
  App.vue (2026-07-19 增加 showcase 公开分支)

  拆分说明:
    原 App.vue 把鉴权门 + 9 个 tab + 全局 composables 混在一起,导致
    setup() 无条件执行 — 即使未登录也会触发 dashboard 数据请求。

    改造:
      - App.vue 只负责"鉴权门 + 路由 switch"
      - DashboardView.vue 承接原 dashboard 全部内容(TopBar/Sidebar/9 tab/轮询)
      - 用 v-if 真正懒挂载:!isAuthed → 只渲染 LoginView,DashboardView 完全不创建

    2026-07-19 增加 ShowcaseView 分支:
      - 路由 /index (name='showcase') → ShowcaseView,不受鉴权门控制
      - 任何路径包括未登录,只要 route.name === 'showcase' 就走对外展示页
-->
<template>
  <!-- 2026-07-19：对外展示首页(/index) — 不受鉴权门控制,访客可直访 -->
  <ShowcaseView v-if="route.name === 'showcase'" />
  <LoginView v-else-if="!isAuthed" />
  <DashboardView v-else />
</template>

<script setup>
import { useRoute } from 'vue-router'
import LoginView from './components/LoginView.vue'
import DashboardView from './components/DashboardView.vue'
import ShowcaseView from './components/ShowcaseView.vue'
import { useAuth } from './composables/useAuth.js'

const route = useRoute()
const { isAuthed } = useAuth()
</script>

<style>
/* 顶层样式由各子组件自带,这里仅放兜底 */
html, body, #app { margin: 0; padding: 0; height: 100%; }
</style>
