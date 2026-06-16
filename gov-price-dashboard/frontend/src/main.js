import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { registerGovPriceTheme } from './composables/useEchartsTheme'

// 注册 ECharts 统一主题（启动时一次即可）
registerGovPriceTheme()

createApp(App).mount('#app')
