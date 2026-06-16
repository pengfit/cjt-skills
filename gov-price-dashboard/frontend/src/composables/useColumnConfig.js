import { ref } from 'vue'

/**
 * 表格列配置：可见列 + 排序 + 列宽
 * 内置 colConfig 弹窗状态
 */
const DEFAULT_COLUMNS = [
  { key: 'breed',    label: '产品名称', sortable: true,  visible: true,  width: 180 },
  { key: 'price',    label: '价格',     sortable: true,  visible: true,  width: 110 },
  { key: 'attr',     label: '属性',     sortable: false, visible: false, width: 220 },
  { key: 'unit',     label: '单位',     sortable: false, visible: true,  width: 60  },
  { key: 'date',     label: '日期',     sortable: true,  visible: true,  width: 95  },
  { key: 'category', label: '分类',     sortable: true,  visible: true,  width: 120 },
]

export function useColumnConfig() {
  const allColumns = ref(DEFAULT_COLUMNS.map(c => ({ ...c })))
  const showColConfig = ref(false)

  const visibleColumns = ref([])

  function toggleColumn(key) {
    const col = allColumns.value.find(c => c.key === key)
    if (col) col.visible = !col.visible
  }

  function isVisible(key) {
    return allColumns.value.find(c => c.key === key)?.visible ?? true
  }

  return { allColumns, visibleColumns, showColConfig, toggleColumn, isVisible }
}
