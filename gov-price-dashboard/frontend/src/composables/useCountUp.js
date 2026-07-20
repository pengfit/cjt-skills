/**
 * 数字 count-up 动画 (2026-07-20)
 *
 * IntersectionObserver 触发 + requestAnimationFrame 平滑动画
 * ease-out cubic 缓动
 *
 * 用法:
 *   const { el, trigger } = useCountUp({ duration: 1500 })
 *   <div :ref="el">{{ g.metric }}</div>  // 元素进入视口时自动从 0 数到目标
 */
import { ref } from 'vue'

/** 解析 metric 字符串 → {prefix, num, suffix, isCountable}
 * '1天'   → {prefix:'', num:1,   suffix:'天', isCountable:true}
 * '10x'   → {prefix:'', num:10,  suffix:'x', isCountable:true}
 * '0→1'   → {isCountable:false}  (含箭头, 不数)
 * '17'    → {prefix:'', num:17,  suffix:'',  isCountable:true}
 * '9,931' → {prefix:'', num:9931,suffix:'',  isCountable:true}
 * '7×24'  → {isCountable:false}  (× 不在数字字符集)
 */
export function parseMetric(metric) {
  if (typeof metric !== 'string') return { isCountable: false }
  // 匹配开头的可选非数字 + 数字(带千分位) + 结尾的可选非数字
  const m = metric.match(/^([^\d]*?)(\d{1,3}(?:,\d{3})*|\d+)([^\d]*)$/)
  if (!m) return { isCountable: false }
  const [, prefix, numStr, suffix] = m
  const num = parseInt(numStr.replace(/,/g, ''), 10)
  return {
    isCountable: true,
    prefix,
    suffix,
    num,
    format: (n) => numStr.includes(',') ? n.toLocaleString() : String(n),
  }
}

export function useCountUp(options = {}) {
  const { duration = 1500, threshold = 0.3 } = options
  const el = ref(null)
  const started = ref(false)

  const start = () => {
    if (started.value) return
    started.value = true
    if (!el.value) return
    const target = el.value.dataset.countTarget
    if (!target) return
    const targetNum = parseFloat(target)
    if (isNaN(targetNum)) return
    const t0 = performance.now()
    const step = (now) => {
      const p = Math.min((now - t0) / duration, 1)
      // ease-out cubic
      const eased = 1 - Math.pow(1 - p, 3)
      const v = p < 1 ? Math.round(targetNum * eased) : targetNum
      const prefix = el.value.dataset.countPrefix || ''
      const suffix = el.value.dataset.countSuffix || ''
      el.value.textContent = prefix + v + suffix
      if (p < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }

  const setup = () => {
    if (!el.value) return
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting && !started.value) {
            start()
            obs.disconnect()
          }
        })
      },
      { threshold }
    )
    obs.observe(el.value)
  }

  return { el, start, setup, started }
}
