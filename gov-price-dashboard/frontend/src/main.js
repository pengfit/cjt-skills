import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { registerGovPriceTheme } from './composables/useEchartsTheme'
import router from './router'
// 2026-07-19 鉴权：注册全局 axios 拦截器(side-effect import)
import './composables/useApi.js'

// 注册 ECharts 统一主题（启动时一次即可，echarts 走懒加载所以 async）
// fire-and-forget：组件 init 时也会 await，主题就绪前不阻塞 UI
registerGovPriceTheme()

// 旧 ?tab=xxx 兼容由 router.beforeEach 守卫处理
const app = createApp(App)
app.use(router)
app.mount('#app')
