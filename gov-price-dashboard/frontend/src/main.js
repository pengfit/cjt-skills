import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { registerGovPriceTheme } from './composables/useEchartsTheme'
import router from './router'
// 2026-07-19 鉴权：注册全局 axios 拦截器(side-effect import)
import './composables/useApi.js'

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

// 旧 ?tab=xxx 兼容由 router.beforeEach 守卫处理
const app = createApp(App)
app.use(router)
app.mount('#app')
