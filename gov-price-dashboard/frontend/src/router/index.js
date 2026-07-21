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
  // 2026-07-21: /showcase 改名为 /home; HomeView.vue (公开 landing), /index → /cockpit (主应用)
  { path: '/home', name: 'home', component: () => import('../components/HomeView.vue'), meta: { public: true } },
  // 2026-07-21: /market 市场行情公开页 (涨跌幅 / 热门品类 / 热力图), 不鉴权
  { path: '/market', name: 'market', component: () => import('../components/MarketView.vue'), meta: { public: true } },
  // 2026-07-21: /showcase 301 跳 /home (旧链接兼容)
  { path: '/showcase', redirect: '/home' },
  // 2026-07-21: /home 是公开 landing, /index 跳到主应用 dashboard
  { path: '/index', redirect: '/cockpit' },
  // 2026-07-20 #19 友好 404 页: 拼错 URL 渲染此组件, 而不是 redirect
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('../components/NotFoundView.vue') },
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
  { path: '/', redirect: '/home' },
  // 2026-07-20 #19 友好 404 页: catch-all 渲染 NotFoundView 组件 (替代原 redirect)
  // 注: NotFoundView 路由已在前面 /showcase 路由旁注册
] 

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    return { top: 0 }
  },
})

// 守卫拦截:
//   1) 兼容旧 ?tab=xxx URL → 重定向到新路径, 丢弃 tab 参数
//   2) /home 公开首页: 清理 date_from / date_to (不属于这个页面) + 自动加 v=时间戳 cache buster
//      - 防止分享链接把 ListView/CockpitView/Rules 的筛选参数串到 /showcase
//      - v=时间戳让浏览器/CDN 视为新 URL, 强制拉取最新内容, 避免旧缓存
//   3) 其它路由 (含 /list /cockpit /rules /breed-detail): 保留 date_from / date_to 不动
const INDEX_ONLY_KEYS = new Set(['date_from', 'date_to', 'v'])

router.beforeEach((to) => {
  // 1) 旧 ?tab=xxx 重定向
  const tab = to.query.tab
  if (tab && TAB_KEYS.has(tab)) {
    const target = TAB_ROUTES.find(r => r.key === tab)
    const { tab: _, ...rest } = to.query
    return { path: target.path, query: rest }
  }

  // 2) /home 路由清理 + cache buster (2026-07-20 19:16 BUG 修: 已有 v= 则放行, 避免死循环)
  if (to.name === 'home') {
    // 已有 v= 时间戳 → 直接放行, 不再 return (return 会触发新导航 → 守卫重跑 → 死循环)
    if (to.query.v) return

    const cleaned = {}
    let changed = false
    for (const [k, v] of Object.entries(to.query)) {
      if (INDEX_ONLY_KEYS.has(k)) {
        changed = true
      } else {
        cleaned[k] = v
      }
    }
    if (!('v' in cleaned)) {
      cleaned.v = String(Date.now())
      changed = true
    }
    if (changed) {
      return { path: to.path, query: cleaned }
    }
  }
})

export function legacyTabPath(tab) {
  const t = TAB_ROUTES.find(r => r.key === tab)
  return t ? t.path : '/cockpit'
}

export default router
