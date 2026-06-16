import { ref, watch } from 'vue'

/**
 * Tab 状态管理：curTab + URL 同步 + localStorage 回退 + 切 tab 自动关闭移动端 sidebar
 */
const TAB_LIST = [
  { key: 'cockpit',   label: '驾驶舱',   group: '总览' },
  { key: 'list',      label: '全部数据', group: '业务查价' },
  { key: 'category',  label: '全部类别', group: '业务查价' },
  { key: 'dist',      label: '价格分布', group: '业务查价' },
  { key: 'sync',      label: '数据同步', group: '系统监控' },
  { key: 'health',    label: '数据健康', group: '系统监控' },
  { key: 'breedcat',  label: '品种分类', group: '规则管理' },
  { key: 'rules',     label: '规格解析', group: '规则管理' },
]

function readTabFromUrl() {
  if (typeof window === 'undefined') return 'list'
  const params = new URLSearchParams(window.location.search)
  const t = params.get('tab')
  if (t && TAB_LIST.find(x => x.key === t)) return t
  // 回退到 localStorage
  try {
    const saved = localStorage.getItem('gov_price_curTab')
    if (saved && TAB_LIST.find(x => x.key === saved)) return saved
  } catch { /* localStorage 不可用 */ }
  return 'list'
}

function saveTab(tab) {
  try { localStorage.setItem('gov_price_curTab', tab) } catch { /* ignore */ }
  if (typeof window !== 'undefined') {
    const url = new URL(window.location.href)
    url.searchParams.set('tab', tab)
    window.history.replaceState({}, '', url.toString())
  }
}

export function useTabState() {
  const curTab = ref(readTabFromUrl())
  const mobileSidebarOpen = ref(false)
  const showCmdPalette = ref(false)

  watch(curTab, () => {
    mobileSidebarOpen.value = false
    saveTab(curTab.value)
  })

  function setTab(t) {
    curTab.value = t
  }

  return { curTab, setTab, mobileSidebarOpen, showCmdPalette, TAB_LIST }
}
