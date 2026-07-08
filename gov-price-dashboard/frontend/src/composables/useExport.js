// 通用导出工具：PNG（ECharts getDataURL）+ CSV（自构 + BOM 防 Excel 中文乱码）
//
// 用法：
//   import { exportChartAsPng, exportCsvAsFile } from '@/composables/useExport'
//   exportChartAsPng(chartInstance, 'filename.png')
//   exportCsvAsFile(rows, 'filename.csv')

function _triggerDownload(href, filename) {
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

/**
 * 把 ECharts 实例当前画面导出为 PNG。
 * @param {echarts.ECharts} inst
 * @param {string} filename 例如 'xian-螺纹钢-20260708.png'
 */
export function exportChartAsPng(inst, filename = 'chart.png') {
  if (!inst || typeof inst.getDataURL !== 'function') {
    console.warn('[export] no echarts instance')
    return false
  }
  try {
    const url = inst.getDataURL({
      type: 'png',
      pixelRatio: 2,
      backgroundColor: '#ffffff',
    })
    _triggerDownload(url, filename)
    return true
  } catch (e) {
    console.error('[export] PNG failed:', e)
    return false
  }
}

/**
 * 把二维数组导出为 CSV。前置 BOM 让 Excel 直接识别 UTF-8。
 * @param {string[][]} rows 第一行通常是表头
 * @param {string} filename
 */
export function exportCsvAsFile(rows, filename = 'export.csv') {
  if (!rows || !rows.length) {
    console.warn('[export] empty rows')
    return false
  }
  const escape = (v) => {
    if (v === null || v === undefined) return ''
    const s = String(v)
    // CSV 转义：含逗号/引号/换行 → 用引号包起来，引号自身双写
    if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`
    return s
  }
  const csv = rows.map(r => r.map(escape).join(',')).join('\r\n')
  // \uFEFF = UTF-8 BOM
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  _triggerDownload(url, filename)
  // 释放 URL（IE 需 setTimeout，主流浏览器可立即释放）
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return true
}

/**
 * 给文件名加时间戳后缀（防覆盖）。示例：'螺纹钢' → '螺纹钢-20260708-0930'
 */
export function withTimestamp(name, d = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  const ts = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`
  // 去掉文件系统不友好的字符
  const safe = String(name || 'export').replace(/[\\/:*?"<>|]/g, '_')
  return `${safe}-${ts}`
}