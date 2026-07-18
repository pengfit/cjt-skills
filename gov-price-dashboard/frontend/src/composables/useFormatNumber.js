/**
 * 统一数字格式化(D.2026-07-12 P0)
 *
 * 之前散落在 30+ 处 {{ x.toLocaleString() }} / formatShort(...) / 各处自己拼字符串,
 * 导致有的 `14.02 元` 有的 `¥14.02` 有的 `8.6k` 不一致。
 *
 * 统一接口：
 *   num(value, opts)            —— 整数/记录数/价格（默认带千分位 + 单位）
 *   num.price(value)            —— 价格  ¥14.02
 *   num.compact(value)          —— 紧凑   8.6k / 12w / 1.2亿
 *   num.count(value, suffix)    —— 计数   8,598 条 / 1.2w 条
 *   num.pct(value, digits=1)    —— 百分比 96.5%
 *   num.delta(value, suffix='') —— 涨跌   ↑ +12.3%
 *
 * 所有方法都对 null / undefined / NaN / 0 做安全兜底。
 */
import { computed, unref } from 'vue'

/** 千分位整数(zh-CN locale)。原 toLocaleString() 等价替身 */
function fmtInt(value) {
  const n = Number(value)
  if (!isFinite(n)) return '0'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

/** 价格:统一 ¥14.02 / ¥1,234.56 形式(保留 2 位小数,千分位) */
function fmtPrice(value) {
  const n = Number(value)
  if (!isFinite(n)) return '¥0.00'
  return '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 紧凑 8.6k / 12.3w / 1.2亿 / 9500(< 1w 时显示原值) */
function fmtCompact(value) {
  const n = Number(value)
  if (!isFinite(n)) return '0'
  const abs = Math.abs(n)
  if (abs < 10_000) return n.toLocaleString('zh-CN')
  if (abs < 100_000_000) {
    if (abs < 1_000_000) return (n / 1000).toFixed(abs < 100_000 ? 1 : 0) + 'k'
    if (abs < 10_000_000) return (n / 10_000).toFixed(abs < 1_000_000 ? 1 : 0) + 'w'
    return (n / 10_000).toFixed(0) + 'w'
  }
  return (n / 100_000_000).toFixed(1) + '亿'
}

/** 计数 + 单位:`8,598 条` / `1.2w 条` */
function fmtCount(value, suffix = '') {
  const n = Number(value)
  if (!isFinite(n)) return suffix ? '0 ' + suffix : '0'
  const abs = Math.abs(n)
  const num = abs < 10_000
    ? n.toLocaleString('zh-CN')
    : (abs < 100_000_000 ? fmtCompact(n) : fmtCompact(n))
  return suffix ? `${num} ${suffix}` : num
}

/** 百分比:96.5% */
function fmtPct(value, digits = 1) {
  const n = Number(value)
  if (!isFinite(n)) return '0%'
  return n.toFixed(digits) + '%'
}

/** 涨跌:`↑ +12.3%` / `↓ -3.4%`(原值为绝对差或百分比均可,按调用方约定) */
function fmtDelta(value, suffix = '', digits = 1) {
  const n = Number(value)
  if (!isFinite(n) || n === 0) return '—'
  const arrow = n > 0 ? '↑' : '↓'
  return `${arrow} ${Math.abs(n).toFixed(digits)}${suffix}`
}

/**
 * 通用入口(向后兼容,可单点替换 `x.toLocaleString()`):
 *   num(1234)            -> '1,234'
 *   num(1234.56, { price: true }) -> '¥1,234.56'
 *   num(1234567, { compact: true }) -> '123.5w'
 *   num(96.5, { pct: true }) -> '96.5%'
 */
function num(value, opts = {}) {
  if (opts.price) return fmtPrice(value)
  if (opts.compact) return fmtCompact(value)
  if (opts.pct != null) return fmtPct(value, typeof opts.pct === 'number' ? opts.pct : 1)
  if (opts.count) return fmtCount(value, opts.suffix || '')
  if (opts.delta != null) return fmtDelta(value, opts.suffix || '', typeof opts.delta === 'number' ? opts.delta : 1)
  return fmtInt(value)
}

export function useFormatNumber() {
  return {
    num,
    int: fmtInt,
    price: fmtPrice,
    compact: fmtCompact,
    count: fmtCount,
    pct: fmtPct,
    delta: fmtDelta,
  }
}

/**
 * 给模板用的 reactive 包装:
 *   const { n } = useFormatReactive()
 *   <span>{{ n(item.count, { count: true }) }}</span>
 */
export function useFormatReactive() {
  const fns = useFormatNumber()
  return {
    ...fns,
    // 允许传入 ref/unref,模板里 {{ n(countRef, { compact: true }) }} 直接工作
    n: (v, opts) => num(unref(v), opts),
  }
}

// 货币格式快捷版（直接调用 fmtMoney(value) 返回格式化金额字符串）
// 2026-07-18 补充：BreedDetailView.vue 需要此 export
export function useFormatMoney() {
  return fmtPrice
}

// 同时提供具名常量,方便直接 import { fmtPrice } from '...'
export { num, fmtInt, fmtPrice, fmtCompact, fmtCount, fmtPct, fmtDelta }