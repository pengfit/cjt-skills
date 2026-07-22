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

// 注册 ECharts 统一主题（启动时一次即可，echarts 走懒加载所以 async）
// fire-and-forget：组件 init 时也会 await，主题就绪前不阻塞 UI
registerGovPriceTheme()

// 旧 ?tab=xxx 兼容由 router.beforeEach 守卫处理
const app = createApp(App)
app.use(router)
app.mount('#app')
