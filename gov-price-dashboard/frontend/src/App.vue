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
  <!-- 2026-07-25: 移动端拦截页 — 不需鉴权,放在 LoginView 前面优先渲染 -->
  <MobileBlockedView v-else-if="route.name === 'mobile-blocked'" />
  <!-- 2026-07-29 BUG 修: 访问 / 时 LoginView 闪现
       原因:Vue Router 初次渲染的瞬间 route.name 可能是 undefined,导致上面 4 个公开页 v-else-if 全部不命中,
       落到 !isAuthed → 登录框闪现 → route 解析完变 'home' → HomeView 覆盖
       修复:加 route.name 守卫 —— 路由未解析时不显示登录框(也不显示后台)
            这种瞬间通常 < 1 帧,肉眼看到的"闪现"被消掉 -->
  <LoginView v-else-if="route.name && !isAuthed" />
  <DashboardView v-else />
</template>

<script setup>
import { defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from './composables/useAuth.js'

// 2026-07-28 架构:所有路由级组件统一 defineAsyncComponent — 让 vite 真正能拆 chunk
//   背景:之前 HomeView / MarketView / MobileBlockedView / NotFoundView 是静态 import,
//         router/index.js 的 () => import() 被静态 import 抵消,Vite 警告
//         '[INEFFECTIVE_DYNAMIC_IMPORT]' — 这些组件仍打进主 chunk,首页加载代价高。
//   修复:统一走 defineAsyncComponent,首屏 bundle 只含 router + useAuth。
//         公开页(/home /market)按需加载,后台页(/cockpit /list / ...)也按需加载。
//   设计保留:仍走 App.vue 的 v-if="route.name==='xxx'" 模板,跨 tab 共享 state。
const HomeView = defineAsyncComponent(() => import('./components/HomeView.vue'))
const MarketView = defineAsyncComponent(() => import('./components/MarketView.vue'))
const MobileBlockedView = defineAsyncComponent(() => import('./components/MobileBlockedView.vue'))
const NotFoundView = defineAsyncComponent(() => import('./components/NotFoundView.vue'))
const DashboardView = defineAsyncComponent(() => import('./components/DashboardView.vue'))
const LoginView = defineAsyncComponent(() => import('./components/LoginView.vue'))

const route = useRoute()
const { isAuthed } = useAuth()

</script>

<style>
/* 顶层样式由各子组件自带,这里仅放兜底 */
html, body, #app { margin: 0; padding: 0; height: 100%; }
</style>
