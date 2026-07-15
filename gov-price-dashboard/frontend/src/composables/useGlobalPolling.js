import { ref, watch, onUnmounted } from 'vue'

/**
 * 全局轮询调度器(P0-2)
 *
 * 把原本散落在 App.vue(TopBar alerts) 和 CockpitView(provenance 数据)
 * 的两套 15 分钟 setInterval 合并成单一 tick。
 *
 * - App.vue 持有 `pollingTick` 与 `pollingPaused`
 * - TopBar 调用 `startPolling` / `stopPolling` 控制
 * - 其他 view watch `pollingTick.value` 触发自己的 load
 * - `bumpTick()` 用于手动「立即刷新」,其他 watcher 同步触发
 *
 * 用模块作用域 ref 保证跨组件单例。
 */

const POLL_INTERVAL_MS = 15 * 60 * 1000  // 15 分钟,与城市检测 cron 节拍对齐

const _tick = ref(0)
const _paused = ref(false)
let _timer = null

function startPolling() {
  stopPolling()
  _timer = setInterval(() => {
    if (_paused.value) return
    _tick.value++
  }, POLL_INTERVAL_MS)
}

function stopPolling() {
  if (_timer) {
    clearInterval(_timer)
    _timer = null
  }
}

function bumpTick() {
  _tick.value++
}

function togglePaused() {
  _paused.value = !_paused.value
}

export function useGlobalPolling() {
  return {
    pollingTick: _tick,
    pollingPaused: _paused,
    POLL_INTERVAL_MS,
    startPolling,
    stopPolling,
    bumpTick,
    togglePaused,
  }
}
