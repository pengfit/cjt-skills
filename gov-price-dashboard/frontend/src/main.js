import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { registerGovPriceTheme } from './composables/useEchartsTheme'
import router from './router'

// 注册 ECharts 统一主题（启动时一次即可）
registerGovPriceTheme()

// 旧 ?tab=xxx 兼容由 router.beforeEach 守卫处理
const app = createApp(App)
app.use(router)
app.mount('#app')
