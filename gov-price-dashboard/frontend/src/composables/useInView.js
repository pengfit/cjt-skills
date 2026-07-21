import { onMounted, onUnmounted, ref } from 'vue'

/**
 * 进入视口检测（一次性触发，进入后断开观察）。
 * 用法：
 *   const { target, inView } = useInView({ threshold: 0.15 })
 *   <section ref="target" :class="{ 'in-view': inView }">
 *
 * 进入视口后,子组件可通过 CSS class `in-view` 触发进入动画。
 */
export function useInView(options = { threshold: 0.15 }) {
  const target = ref(null)
  const inView = ref(false)
  let observer = null

  onMounted(() => {
    if (!target.value || typeof IntersectionObserver === 'undefined') {
      // SSR / 旧浏览器兜底：直接视为可见
      inView.value = true
      return
    }
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          inView.value = true
          observer.unobserve(entry.target)
        }
      }
    }, options)
    observer.observe(target.value)
  })

  onUnmounted(() => {
    if (observer) observer.disconnect()
  })

  return { target, inView }
}
