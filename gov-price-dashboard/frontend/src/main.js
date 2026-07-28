import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { registerGovPriceTheme } from './composables/useEchartsTheme'
import router from './router'
// 2026-07-19 鉴权：注册全局 axios 拦截器(side-effect import)
import './composables/useApi.js'

// 2026-07-26 #SEO: @unhead/vue@3.2.3 注册
//   跟 v1 不一样 — 没有 app.use(createHead()) 这种入口,要靠 provide + headSymbol 让
//   injectHead() 在 HomeView/MarketView 的 setup 阶段拿到实例。
//   不注册 → injectHead() 返回 undefined → useHead() 抛错 → Vue mount 失败 → 全页空白。
//   教训：以后改 SEO 这种跨包改动，构建完必须实际访问页面，不能只看 dist 输出。
import { createUnhead, headSymbol } from '@unhead/vue'
const unhead = createUnhead()

// 2026-07-22: 关闭浏览器自动滚动恢复,避免刷新 /home 时滚到上次位置
// 浏览器默认 'auto' 会恢复刷新前的 scrollY,Vue Router 的 scrollBehavior 无法覆盖
if ('scrollRestoration' in history) {
  history.scrollRestoration = 'manual'
}

// 2026-07-23 /market 路由 fetch 拦截器:
//   在 /market 路由下,只允许调用 /api/market/* 接口,其他 /api/* 一律拒绝并 console.warn
//   隔离范围:防止误调 /api/list/* /api/skill-updates 等非 /market 接口
//   注意:必须在 Vue 应用创建前安装,才能拦截所有 fetch 调用
const _originalFetch = window.fetch.bind(window)
window.fetch = function (input, init) {
  const isMarketRoute =
    window.location.pathname === '/market' ||
    window.location.pathname.startsWith('/market/')
  if (isMarketRoute) {
    const url = typeof input === 'string' ? input : input?.url || ''
    const isApiCall = url.includes('/api/')
    const isMarketApi = url.includes('/api/market/')
    if (isApiCall && !isMarketApi) {
      console.warn(
        `[market-guard] /market 页面拒绝调用 ${url}` +
        '\n  原因:该接口不属于 /market 范畴,防止数据层污染'
      )
      return Promise.reject(new Error(`market-guard blocked: ${url}`))
    }
  }
  return _originalFetch(input, init)
}

// 注册 ECharts 统一主题（启动时一次即可，echarts 走懒加载所以 async）
// fire-and-forget：组件 init 时也会 await，主题就绪前不阻塞 UI
registerGovPriceTheme()

// 2026-07-28:Element Plus 国际化（后台页面全是中文,zh-CN）
import zhCn from 'element-plus/es/locale/lang/zh-cn'

// 旧 ?tab=xxx 兼容由 router.beforeEach 守卫处理
const app = createApp(App)
app.use(router)
// 2026-07-26 #SEO: 把 unhead 实例 provide 到根,让 useHead() 在 setup 阶段能 injectHead() 拿到
app.provide(headSymbol, unhead)
app.mount('#app')
