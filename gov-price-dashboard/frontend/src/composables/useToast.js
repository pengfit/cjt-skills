import { ref } from 'vue'

/**
 * 轻量 Toast：全站共用同一个 toast 状态
 */
const toast = ref({ show: false, msg: '' })
let _timer = null

export function useToast() {
  function show(msg, durationMs = 3000) {
    toast.value = { show: true, msg }
    if (_timer) clearTimeout(_timer)
    _timer = setTimeout(() => { toast.value.show = false }, durationMs)
  }
  return { toast, show }
}
