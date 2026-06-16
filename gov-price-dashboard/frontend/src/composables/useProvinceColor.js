/**
 * 省份色板（数据驱动色）—— 19 省份 + 自动分配
 * 颜色应跟整体 UI 协调，因此固定一套调过的色板
 */
const PROVINCE_COLORS = {
  '辽宁': '#4a90d9', '江苏': '#50c5a8', '新疆': '#f5a623', '陕西': '#e85555',
  '江西': '#9b59b6', '黑龙江': '#34495e', '青海': '#e67e22', '山东': '#1abc9c',
  '上海': '#3498db', '吉林': '#95a5a6', '广东': '#e74c3c', '北京': '#2ecc71',
  '海南': '#f39c12', '重庆': '#c0392b', '宁夏': '#7f8c8d', '湖南': '#8e44ad',
  '内蒙古': '#16a085', '河南': '#d35400', '贵州': '#cf5c2a',
}
const _colorList = Object.values(PROVINCE_COLORS)
let _idx = 0
const _cache = {}

export function getProvinceColor(province) {
  if (!province) return '#94a3b8'
  if (PROVINCE_COLORS[province]) return PROVINCE_COLORS[province]
  if (_cache[province]) return _cache[province]
  _cache[province] = _colorList[_idx % _colorList.length]
  _idx++
  return _cache[province]
}
