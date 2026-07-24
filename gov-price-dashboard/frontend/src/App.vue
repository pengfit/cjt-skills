<!--
  App.vue (2026-07-19 增加 showcase 公开分支)
  2026-07-21 改造: /showcase 重命名为 /home,组件 ShowcaseView → HomeView
  2026-07-21 改造: 新增 /market 公开市场行情页 (MarketView)
-->
<template>
  <!-- 2026-07-21: /market 市场行情公开页 — 不受鉴权门控制，访客可直访 -->
  <MarketView v-if="route.name === 'market'" />
  <!-- 2026-07-23 v2: /home 恢复公开(友反馈 — 首页作为落地页必须访客直访) -->
  <HomeView v-else-if="route.name === 'home'" />
  <NotFoundView v-else-if="route.name === 'not-found'" />
  <LoginView v-else-if="!isAuthed" />
  <DashboardView v-else />
</template>

<script setup>
import { defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import HomeView from './components/HomeView.vue'
import MarketView from './components/MarketView.vue'
import NotFoundView from './components/NotFoundView.vue'
import { useAuth } from './composables/useAuth.js'

// 2026-07-24 架构修复: DashboardView / LoginView 改为异步加载
//   背景: App.vue 之前静态 import DashboardView,把 useListSearch.js(含 /api/list/* 调用)全压进首屏 bundle。
//         /market 公开页加载时,这部分代码会被 evaluate,axios 模块被提前初始化 → 下次改一行顶层 fetch 就可能误触发 list 接口。
//         架构上不对 —— /market /home 公开页不需要 ListView 的代码。
//   修复: defineAsyncComponent 拆分,只有路由需要时才下载。首屏 bundle 不含 ListView / SearchHistory / Export 等代码。
const DashboardView = defineAsyncComponent(() => import('./components/DashboardView.vue'))
const LoginView = defineAsyncComponent(() => import('./components/LoginView.vue'))

const route = useRoute()
const { isAuthed } = useAuth()

</script>

<style>
/* 顶层样式由各子组件自带,这里仅放兜底 */
html, body, #app { margin: 0; padding: 0; height: 100%; }
</style>
