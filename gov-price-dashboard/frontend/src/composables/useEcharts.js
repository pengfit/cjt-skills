/**
 * 单点 ECharts 懒加载
 *
 * ECharts ~2.7 MB，是主 chunk 的最大负担。
 * 用 dynamic import 让 Vite 自动 split 成独立 chunk，
 * 主 bundle 只在第一次图表渲染时按需下载。
 *
 * 用法：
 *   // 1) 异步拿 echarts 模块
 *   const echarts = await useEcharts()
 *   const chart = echarts.init(el)
 *
 *   // 2) 仅注册主题（theme 注册需 module 已加载）
 *   const echarts = await useEcharts()
 *   echarts.registerTheme(THEME_NAME, theme)
 *
 * 注意：返回的是 ES module 命名空间对象，访问成员需 echarts.xxx。
 */

let _promise = null

export function useEcharts() {
  if (!_promise) {
    _promise = import('echarts').then(m => m.default || m)
  }
  return _promise
}