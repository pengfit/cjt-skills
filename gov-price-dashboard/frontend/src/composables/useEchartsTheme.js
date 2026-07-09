import { useEcharts } from './useEcharts'

/**
 * 材价通 ECharts 统一主题
 * - 浅色背景 + 深色文字（与 :root CSS 变量一致）
 * - 调色板：blue / green / orange / purple / cyan / red
 * - axisLine/splitLine 走中性灰
 * - tooltip 浅底深字 + 阴影
 *
 * 使用：
 *   import { registerGovPriceTheme, GOV_PRICE_PALETTE } from '@/composables/useEchartsTheme'
 *   await registerGovPriceTheme()  // 调一次（main.js / 组件 onMounted）
 *   const chart = echarts.init(el, 'govPrice')
 *
 * 注意：registerGovPriceTheme() 是 async，因为 echarts 走懒加载。
 */
export const GOV_PRICE_PALETTE = [
  '#2563eb', // primary blue
  '#16a34a', // success green
  '#ea580c', // warning orange
  '#7c3aed', // purple
  '#0891b2', // cyan
  '#dc2626', // danger red
  '#0d9488', // teal
  '#d97706', // amber
]

const THEME_NAME = 'govPrice'

let _registered = false
let _registrationPromise = null

export function registerGovPriceTheme() {
  if (_registrationPromise) return _registrationPromise
  _registrationPromise = (async () => {
    const echarts = await useEcharts()
    if (_registered) return
    _registered = true
    const theme = {
      color: GOV_PRICE_PALETTE,
      backgroundColor: 'transparent',
      textStyle: {
        color: '#0f172a',
        fontFamily: 'PingFang SC, Microsoft YaHei, -apple-system, sans-serif',
      },
      title: {
        textStyle: { color: '#0f172a', fontWeight: 600 },
        subtextStyle: { color: '#475569' },
      },
      legend: {
        textStyle: { color: '#475569' },
        icon: 'roundRect',
        itemWidth: 10,
        itemHeight: 10,
      },
      grid: { left: 50, right: 24, top: 36, bottom: 32, containLabel: true },
      categoryAxis: {
        axisLine: { lineStyle: { color: '#cbd5e1' } },
        axisTick: { lineStyle: { color: '#cbd5e1' } },
        axisLabel: { color: '#475569' },
        splitLine: { show: false, lineStyle: { color: '#e2e8f0' } },
      },
      valueAxis: {
        axisLine: { show: false, lineStyle: { color: '#cbd5e1' } },
        axisTick: { show: false },
        axisLabel: { color: '#475569' },
        splitLine: { lineStyle: { color: '#e2e8f0' } },
      },
      tooltip: {
        backgroundColor: 'rgba(255, 255, 255, 0.98)',
        borderColor: '#cbd5e1',
        borderWidth: 1,
        textStyle: { color: '#0f172a', fontSize: 12 },
        extraCssText: 'box-shadow: 0 4px 12px rgba(15, 23, 42, 0.10); border-radius: 6px;',
      },
      line: {
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2 },
      },
      bar: {
        itemStyle: { borderRadius: [3, 3, 0, 0] },
      },
      pie: {
        itemStyle: { borderColor: '#ffffff', borderWidth: 1 },
      },
      scatter: {
        itemStyle: { opacity: 0.85 },
      },
    }
    echarts.registerTheme(THEME_NAME, theme)
  })()
  return _registrationPromise
}

export function getGovPriceTheme() {
  return THEME_NAME
}