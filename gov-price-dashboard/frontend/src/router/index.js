import { createRouter, createWebHistory } from 'vue-router'

// 路由表：仅做 "path ↔ name" 映射
// 实际渲染逻辑在 App.vue 中由 `v-if="route.name === 'xxx'"` 承担
// 这样保留跨 tab 共享 state，避免大改
//
// 顺序：与原 TAB_LIST 完全一致；数字键 1-9 / ⌘K 索引都基于此顺序
export const TAB_ROUTES = [
  { key: 'cockpit',  label: '驾驶舱',     path: '/cockpit' },
  { key: 'list',     label: '全部数据',   path: '/list' },
  { key: 'category', label: '全部类别',   path: '/category' },
  { key: 'dist',     label: '价格分布',   path: '/distribution' },
  { key: 'trend',    label: '价格走势',   path: '/trend' },
  { key: 'sync',     label: '数据同步',   path: '/sync' },
  { key: 'health',   label: '数据健康',   path: '/health' },
  { key: 'rules',    label: '规格解析',   path: '/spec-rules' },
  { key: 'taxonomy', label: '分类体系',   path: '/taxonomy' },
]

const TAB_KEYS = new Set(TAB_ROUTES.map(r => r.key))

// 一个空组件，所有 tab 共用（v-if 分块仍由 App.vue 渲染）
const TabsLayout = { name: 'TabsLayout', template: '<router-view />' }

const routes = [
  // 2026-07-19 鉴权:登录页放在最前,公开
  { path: '/login', name: 'login', component: () => import('../components/LoginView.vue'), meta: { public: true } },
  // 2026-07-19 对外展示首页(/index),公开,不鉴权
  { path: '/index', name: 'showcase', component: () => import('../components/ShowcaseView.vue'), meta: { public: true } },
  ...TAB_ROUTES.map(r => ({
    path: r.path,
    name: r.key,
    component: TabsLayout,
    meta: { key: r.key, label: r.label },
  })),
  // 跨页详情中心 (2026-07-15 改造 A) — 单页,不走 currentTab
  // /breed-detail?breed=X&l3=Y&province=Z&city=W[&from=list|taxonomy|spec-rules]
  // 用「直接挂组件」而非 TabsLayout,以免 router-view 二级路由丢渲染
  { path: '/breed-detail', name: 'breed-detail', component: () => import('../components/BreedDetailView.vue'), meta: { standalone: true } },
  { path: '/', redirect: '/cockpit' },
  { path: '/:pathMatch(.*)*', redirect: '/cockpit' },
] 

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    return { top: 0 }
  },
})

// 兼容旧 ?tab=xxx URL：守卫拦截，重定向到新路径，同时丢弃 tab 参数
router.beforeEach((to) => {
  const tab = to.query.tab
  if (tab && TAB_KEYS.has(tab)) {
    const target = TAB_ROUTES.find(r => r.key === tab)
    const { tab: _, ...rest } = to.query
    return { path: target.path, query: rest }
  }
})

export function legacyTabPath(tab) {
  const t = TAB_ROUTES.find(r => r.key === tab)
  return t ? t.path : '/cockpit'
}

export default router
