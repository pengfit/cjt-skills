<template>
  <div class="dashboard">

    <!-- ========== TOP BAR ========== -->
    <header class="top-bar">
      <div class="top-bar-left">
        <svg class="top-bar-icon" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
          <rect width="64" height="64" rx="14" fill="rgba(15,23,42,0.9)"/>
          <circle cx="32" cy="32" r="26" fill="none" stroke="rgba(56,189,248,0.2)" stroke-width="5"/>
          <circle cx="32" cy="32" r="26" fill="none" stroke="#38bdf8" stroke-width="5" stroke-linecap="round" stroke-dasharray="110 53" transform="rotate(-90 32 32)"/>
          <rect x="16" y="16" width="32" height="32" rx="5" fill="rgba(56,189,248,0.05)" stroke="rgba(56,189,248,0.3)" stroke-width="2"/>
          <rect x="20" y="40" width="5" height="8" rx="2" fill="#38bdf8" opacity="0.6"/>
          <rect x="27" y="34" width="5" height="14" rx="2" fill="#38bdf8" opacity="0.75"/>
          <rect x="34" y="26" width="5" height="22" rx="2" fill="#38bdf8" opacity="0.9"/>
          <rect x="41" y="18" width="5" height="30" rx="2" fill="#6366f1"/>
          <polyline points="17,43 23,38 29,34 35,29 41,23 47,18" fill="none" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="47" cy="18" r="4" fill="#38bdf8"/>
        </svg>
        <span class="top-bar-brand">采价通</span>
        <button class="nav-tab" :class="{ active: curTab === 'list' }" @click="curTab = 'list'; saveTab('list')">全部数据</button>
        <button class="nav-tab" :class="{ active: curTab === 'category' }" @click="curTab = 'category'; saveTab('category')">全部类别</button>
        <button class="nav-tab" :class="{ active: curTab === 'dist' }" @click="curTab = 'dist'; saveTab('dist')">数据统计</button>
        <button class="nav-tab" :class="{ active: curTab === 'provenance' }" @click="curTab = 'provenance'; saveTab('provenance')">数据清洗</button>
        <button class="nav-tab" :class="{ active: curTab === 'breedcat' }" @click="curTab = 'breedcat'; saveTab('breedcat')">品种分类</button>
        <button class="nav-tab" :class="{ active: curTab === 'rules' }" @click="curTab = 'rules'; saveTab('rules')">规格解析</button>
      </div>
      <div class="top-bar-meta">
        <span class="meta-item">
          <span class="meta-label">数据总量</span>
          <span class="meta-value">{{ overview.total_docs.toLocaleString() }}</span>
        </span>
        <span class="meta-sep">|</span>
        <span class="meta-item">
          <span class="meta-label">省份</span>
          <span class="meta-value">{{ overview.total_provinces }}</span>
        </span>
        <span class="meta-sep">|</span>
        <span class="meta-item">
          <span class="meta-label">城市</span>
          <span class="meta-value">{{ overview.total_cities }}</span>
        </span>
        <span class="meta-sep">|</span>

      </div>
    </header>

    <!-- Filter Bar (full-width, above main content) -->
    <template v-if="curTab === 'list'">
    <div class="filter-bar">
      <input
        class="filter-bar-input"
        v-model="searchKeyword"
        placeholder="🔍 产品名称 / 关键词"
        @keyup.enter="doSearch()"
        @input="onKeywordInput"
      />
      <button class="btn-more" @click="showDrawer = true">更多筛选 ▸</button>

      <!-- Active Filter Tags (inside filter-bar) -->
      <div class="filter-tags" v-if="searchKeyword || searchProvince || searchCity || searchCounty">
        <span class="filter-tag" v-if="searchKeyword">
          <strong>产品名称</strong>
          <em>{{ searchKeyword }}</em>
          <span class="tag-remove" @click="searchKeyword = ''; doSearch()">✕</span>
        </span>
        <span class="filter-tag" v-if="searchProvince">
          <strong>省份</strong>
          <em>{{ searchProvince }}</em>
          <span class="tag-remove" @click="searchProvince = ''; searchCity = ''; searchCounty = ''; doSearch()">✕</span>
        </span>
        <span class="filter-tag" v-if="searchCity">
          <strong>城市</strong>
          <em>{{ searchCity }}</em>
          <span class="tag-remove" @click="searchCity = ''; searchCounty = ''; doSearch()">✕</span>
        </span>
        <span class="filter-tag" v-if="searchCategory">
          <strong>分类</strong>
          <em>{{ searchCategory }}</em>
          <span class="tag-remove" @click="searchCategory = ''; doSearch()">✕</span>
        </span>
        <span class="filter-tag" v-if="searchCounty">
          <strong>区县</strong>
          <em>{{ searchCounty }}</em>
          <span class="tag-remove" @click="searchCounty = ''; doSearch()">✕</span>
        </span>
        <span class="filter-tag-clear" @click="resetSearch">清空全部</span>
      </div>
    </div>

    <!-- Filter Drawer (slide-in from right) -->
    <Transition name="drawer">
      <div class="drawer" v-if="showDrawer">
        <div class="drawer-header">
          <span>更多筛选</span>
          <span class="drawer-close" @click="showDrawer = false">✕</span>
        </div>
        <div class="drawer-body">
          <div class="filter-group">
            <label class="filter-label">省份</label>
            <CustomSelect
              v-model="searchProvince"
              :options="(overview.by_province || []).map(p => ({ key: p.province, count: p.count }))"
              placeholder="全部省份"
              :searchable="true"
              @change="() => { onProvinceChange(); doSearch(); }"
            />
          </div>
          <div class="filter-group">
            <label class="filter-label">城市</label>
            <CustomSelect
              v-model="searchCity"
              :options="filteredCities.map(c => ({ key: c.key, count: c.count }))"
              :disabled="!searchProvince"
              placeholder="全部城市"
              :searchable="true"
              @change="doSearch"
            />
          </div>
          <div class="filter-group">
            <label class="filter-label">区县</label>
            <CustomSelect
              v-model="searchCounty"
              :options="filteredCounties.map(c => ({ key: c.key, count: c.count }))"
              placeholder="全部区县"
              :searchable="true"
              @change="doSearch"
            />
          </div>
          <div class="filter-group">
            <label class="filter-label">分类</label>
            <CustomSelect
              v-model="searchCategory"
              :options="categoryOptions"
              placeholder="全部分类"
              :searchable="true"
              @change="doSearch"
            />
          </div>
          <div class="filter-group">
            <label class="filter-label">搜索历史</label>
            <div class="search-history-bar" v-if="searchHistory.length && !searchKeyword">
              <span
                v-for="h in searchHistory.slice(0,8)"
                :key="h"
                class="history-chip"
                @click="searchKeyword = h; doSearch()"
              >{{ h }}</span>
              <span class="history-clear" @click="clearHistory()">清空历史</span>
            </div>
          </div>
        </div>
        <div class="drawer-footer">
          <button class="btn-primary" @click="() => { showDrawer = false; doSearch(); }">🔍 确定</button>
          <button class="btn-ghost" @click="resetSearch">重置</button>
        </div>
      </div>
    </Transition>

      <!-- RIGHT: Content Area -->
      <main class="content-area">

        <!-- Toolbar (standalone, outside Transition) -->
        <!-- ========== TABLE or CHART or LOADING or EMPTY ========== -->
        <Transition name="content-fade">
        <div>

        <!-- Skeleton loading (rows inside table wrapper) -->
        <div class="content-card" v-if="loading">
          <div class="skeleton-header">
            <div class="skeleton-col" v-for="col in visibleColumns" :key="col.key" :style="{ width: col.width + 'px' }"></div>
          </div>
          <div class="skeleton-row" v-for="i in 8" :key="i">
            <div class="skeleton-col" v-for="col in visibleColumns" :key="col.key" :style="{ width: col.width + 'px' }"></div>
          </div>
          <div class="skeleton-footer"></div>
        </div>

        <!-- Error state -->
        <div v-else-if="searchError" class="error-state">
          <div class="error-icon">⚠️</div>
          <div class="error-title">{{ searchError }}</div>
          <div class="error-hint">请检查网络或数据服务是否正常</div>
          <button class="btn-primary error-retry-btn" @click="doSearch()">🔄 重试</button>
        </div>

        <!-- Empty state -->
        <div v-else-if="!searchResult.data || !searchResult.data.length" class="empty-state">
          <div class="empty-icon">🗺️</div>
          <div class="empty-title">暂无数据</div>
          <div class="empty-hint">
            可能原因：
            <div>· 该省份暂无此类产品的价格记录</div>
            <div>· 数据更新时间晚于最近日期</div>
            <div class="empty-suggestions">试试：<span class="suggestion-chip" @click="searchKeyword = ''">清空关键词</span><span class="suggestion-chip" @click="searchProvince = ''">切换省份</span><span class="suggestion-chip" @click="searchCategory = ''">全部分类</span></div>
          </div>
        </div>

        <!-- Data Table -->
        <div class="content-card" v-else>
          <div class="table-scroll">
            <table class="result-table">
              <thead>
                <tr>
                  <th
                    v-for="col in visibleColumns"
                    :key="col.key"
                    :class="{ sorted: sortKey === col.key, sortable: col.sortable }"
                    @click="col.sortable && sortBy(col.key)"
                  >
                    {{ col.label }}
                    <span v-if="col.sortable" class="sort-icon">
                      {{ sortKey === col.key ? (sortDir === 'asc' ? '↑' : '↓') : '↕' }}
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(item, idx) in sortedData"
                  :key="item.id || idx"
                  class="data-row"
                  :class="{ 'stale-row': isStale(item.date) }"
                >
                  <td
                    v-for="col in visibleColumns"
                    :key="col.key"
                    :class="getCellClass(col.key, item)"
                    :title="col.key === 'breed' ? item.breed : col.key === 'spec' ? item.spec_clean : undefined"
                  >
                    <template v-if="col.key === 'breed'">
                      <div class="breed-cell">
                        <span class="breed-name" v-html="highlightKeyword(item.breed)"></span>
                        <div class="breed-meta">
                          <AttrTags :attr="item.attr" />
                          <span class="meta-sep" v-if="item.city">·</span>
                          <span class="meta-tag city-tag" v-if="item.city">{{ item.city }}</span>
                        </div>
                      </div>
                    </template>
                    <template v-else-if="col.key === 'province'"></template>
                    <template v-else-if="col.key === 'city'"></template>
                    <template v-else-if="col.key === 'county'"></template>
                    <template v-else-if="col.key === 'unit'">{{ item.unit }}</template>
                    <template v-else-if="col.key === 'price'">
                      <div class="price-main">{{ fmtCell(item.price) }}</div>
                      <div class="price-tax">{{ fmtCell(item.tax_price) }}</div>
                      <div class="price-change" v-if="getPriceChange(item)" :class="getPriceChange(item).cls" style="pointer-events:none">{{ getPriceChange(item).text }}</div>
                    </template>
                    <template v-else-if="col.key === 'attr'">
                      <div class="attr-cell">
                        <AttrTags :attr="item.attr" />
                      </div>
                    </template>
                    <template v-else-if="col.key === 'date'">
                      <span :class="{ 'stale-date': isStale(item.date) }">{{ staleText(item.date) || item.date || '—' }}</span>
                    </template>
                    <template v-else-if="col.key === 'category'">
                      <span class="cat-badge">{{ item.category || '—' }}</span>
                    </template>
                    <template v-else>{{ item[col.key] ?? '—' }}</template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Pagination -->
          <div class="pagination" v-if="searchResult.pages && searchResult.pages > 1">
            <button class="page-btn nav" :disabled="searchPage <= 1" @click="prevPage()">‹</button>
            <button
              v-for="p in pageRange"
              :key="p"
              class="page-btn"
              :class="{ active: Number(p) === Number(searchPage), ellipsis: p === '...' }"
              :disabled="p === '...'"
              @click="p !== '...' && goToPage(Number(p))"
            >{{ p }}</button>
            <button class="page-btn nav" :disabled="searchPage >= searchResult.pages" @click="nextPage()">›</button>
            <div class="page-jump-wrap">
              <span>跳至</span>
              <input class="page-jump" v-model.number="jumpPage" @keyup.enter="goToPage(jumpPage)" type="number" min="1" :max="searchResult.pages" />
              <span>页</span>
            </div>
            <div class="page-size-wrap">
              <span>每页</span>
              <select class="page-size-select" v-model.number="pageSize" @change="onPageSizeChange">
                <option v-for="s in pageSizeOptions" :key="s" :value="s">{{ s }}</option>
              </select>
              <span>条</span>
            </div>
          </div>
        </div>
        </div>
        </Transition>
      </main>
    </template>

    <!-- Distribution page -->
    <template v-if="curTab === 'dist'">
      <DistributionChart
        :keyword="searchKeyword"
        :province="searchProvince"
        :city="searchCity"
      />
    </template>

    <template v-if="curTab === 'category'">
      <CategoryView />
    </template>

    <template v-if="curTab === 'provenance'">
      <DataProvenanceView />
    </template>

    <template v-if="curTab === 'rules'">
      <VecRulesView />
    </template>

    <template v-if="curTab === 'breedcat'">
      <BreedCategoryRulesView />
    </template>
  </div>

  <!-- Toast -->
  <div v-if="toast.show" class="toast">{{ toast.msg }}</div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import axios from 'axios'
import AttrTags from './components/AttrTags.vue'
import CustomSelect from './components/CustomSelect.vue'
import DistributionChart from './components/DistributionChart.vue'
import CategoryView from './components/CategoryView.vue'
import DataProvenanceView from './components/DataProvenanceView.vue'
import VecRulesView from './components/VecRulesView.vue'
import BreedCategoryRulesView from './components/BreedCategoryRulesView.vue'

const API = import.meta.env.VITE_API_URL || '/api'

// ============================================================
// STATE
// ============================================================
const curTab = ref(localStorage.getItem('gov_cur_tab') || 'list')
function saveTab(tab) { localStorage.setItem('gov_cur_tab', tab) }
const overview = ref({ total_docs: 0, total_provinces: 0, total_cities: 0, avg_price: 0, max_price: 0, min_price: 0, by_province: [] })
const searchKeyword = ref('')
const searchProvince = ref('')
const searchCity = ref('')
const searchCounty = ref('')
const searchCategory = ref('')
const categoryOptions = ref([])
const priceMin = ref('')
const priceMax = ref('')
const searchPage = ref(1)
const loading = ref(false)
const searchResult = ref({})
const cityOptions = ref([])
const countyOptions = ref([])
const provinceCityMap = ref({})
const jumpPage = ref(1)
const debounceTimer = ref(null)
const pageSize = ref(20)
const pageSizeOptions = [20, 50, 100]
const searchHistory = ref(JSON.parse(localStorage.getItem('gov_price_history') || '[]'))

// Sort
const sortKey = ref('')
const sortDir = ref('asc')

// Column config
const showColConfig = ref(false)
const showDrawer = ref(false)
const colConfigRef = ref(null)
const allColumns = ref([
  { key: 'breed',    label: '产品名称',  sortable: true,  visible: true, width: 180 },
  { key: 'price',    label: '价格',      sortable: true,  visible: true, width: 110 },
  { key: 'attr',     label: '属性',      sortable: false, visible: false, width: 220 },

  { key: 'unit',     label: '单位',      sortable: false, visible: true, width: 60  },
  { key: 'date',     label: '日期',      sortable: true,  visible: true, width: 95  },
  { key: 'category', label: '分类',      sortable: true,  visible: true, width: 120 },
])

// Price presets
const pricePresets = [
  { label: '0-500',    min: '0',    max: '500' },
  { label: '500-2k',   min: '500',  max: '2000' },
  { label: '2k-1万',  min: '2000', max: '10000' },
  { label: '>1万',    min: '10000', max: '' },
]

// Toast
const toast = ref({ show: false, msg: '' })
const searchError = ref(false)

// Province colors (palette)
const PROVINCE_COLORS = {
  '辽宁': '#4a90d9', '江苏': '#50c5a8', '新疆': '#f5a623', '陕西': '#e85555',
  '江西': '#9b59b6', '黑龙江': '#34495e', '青海': '#e67e22', '山东': '#1abc9c',
  '上海': '#3498db', '吉林': '#95a5a6', '广东': '#e74c3c', '北京': '#2ecc71',
  '海南': '#f39c12', '重庆': '#c0392b', '宁夏': '#7f8c8d', '湖南': '#8e44ad',
  '内蒙古': '#16a085', '河南': '#d35400', '贵州': '#cf5c2a',
}
let _provinceColorIdx = 0
const _provinceColorList = Object.values(PROVINCE_COLORS)

function getProvinceColor(province) {
  if (PROVINCE_COLORS[province]) return PROVINCE_COLORS[province]
  PROVINCE_COLORS[province] = _provinceColorList[_provinceColorIdx % _provinceColorList.length]
  _provinceColorIdx++
  return PROVINCE_COLORS[province]
}

// ============================================================
// COMPUTED
// ============================================================
const visibleColumns = computed(() => allColumns.value.filter(c => c.visible))

const filteredCities = computed(() => {
  if (!searchProvince.value) return cityOptions.value
  return cityOptions.value.filter(c => c.province === searchProvince.value)
})

const filteredCounties = computed(() => {
  let list = countyOptions.value
  if (searchProvince.value) list = list.filter(c => c.province === searchProvince.value)
  if (searchCity.value) list = list.filter(c => c.city === searchCity.value)
  return list
})

const sortedData = computed(() => {
  const data = searchResult.value.data || []
  if (!sortKey.value) return data
  return [...data].sort((a, b) => {
    let av = a[sortKey.value] ?? ''
    let bv = b[sortKey.value] ?? ''
    av = String(av).toLowerCase()
    bv = String(bv).toLowerCase()
    if (av < bv) return sortDir.value === 'asc' ? -1 : 1
    if (av > bv) return sortDir.value === 'asc' ? 1 : -1
    return 0
  })
})

function onPageSizeChange() {
  searchPage.value = '1'
  jumpPage.value = 1
  doSearch(1)
}

const pageStart = computed(() => {
  const s = (Number(searchPage.value) - 1) * pageSize.value + 1
  return s > 0 ? s.toLocaleString() : '0'
})

const pageEnd = computed(() => {
  const e = Math.min(Number(searchPage.value) * pageSize.value, searchResult.value.total || 0)
  return e.toLocaleString()
})

const pageRange = computed(() => {
  const total = searchResult.value.pages || 1
  const cur = Number(searchPage.value)
  if (total <= 7) {
    return Array.from({length: total}, (_, i) => i + 1)
  }
  const range = []
  if (cur <= 4) {
    for (let i = 1; i <= 5; i++) range.push(i)
    range.push('...')
    range.push(total)
  } else if (cur >= total - 3) {
    range.push(1)
    range.push('...')
    for (let i = total - 4; i <= total; i++) range.push(i)
  } else {
    range.push(1)
    range.push('...')
    for (let i = cur - 1; i <= cur + 1; i++) range.push(i)
    range.push('...')
    range.push(total)
  }
  return range
})

// ============================================================
// ACTIONS
// ============================================================
function sortBy(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
}

function onProvinceChange() {
  searchCity.value = ''
  searchCounty.value = ''
}

function prevPage() {
  if (searchPage.value <= 1) return
  searchPage.value = String(Number(searchPage.value) - 1)
  doSearch(Number(searchPage.value))
}

function nextPage() {
  if (searchPage.value >= searchResult.value.pages) return
  searchPage.value = String(Number(searchPage.value) + 1)
  doSearch(Number(searchPage.value))
}

function goToPage(p) {
  if (p < 1 || p > (searchResult.value.pages || 1)) return
  searchPage.value = String(p)
  doSearch(Number(searchPage.value))
}

async function doSearch(pageOverride) {
  if (!pageOverride) {
    searchPage.value = '1'
    jumpPage.value = 1
    sortKey.value = ''
    sortDir.value = 'asc'
  }
  loading.value = true
  searchError.value = false
  try {
    const params = {}
    if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
    if (searchProvince.value) params.province = searchProvince.value
    if (searchCity.value) params.city = searchCity.value
    if (searchCounty.value) params.county = searchCounty.value
    if (searchCategory.value) params.category = searchCategory.value
    if (priceMin.value) params.price_min = priceMin.value
    if (priceMax.value) params.price_max = priceMax.value
    params.page = Number(pageOverride || searchPage.value)
    params.page_size = Number(pageSize.value)
    if (isNaN(params.page) || params.page < 1) params.page = 1

    const { data: res } = await axios.get(`${API}/search`, { params })
    searchResult.value = res || {}

    // Save search history
    if (searchKeyword.value.trim()) {
      const kw = searchKeyword.value.trim()
      const hist = searchHistory.value.filter(h => h !== kw)
      hist.unshift(kw)
      searchHistory.value = hist.slice(0, 10)
      localStorage.setItem('gov_price_history', JSON.stringify(searchHistory.value))
    }
  } catch (e) {
    searchError.value = true
    showToast('请求失败：' + (e.message || '网络错误'))
  } finally {
    loading.value = false
  }
}

function resetSearch() {
  searchKeyword.value = ''
  searchProvince.value = ''
  searchCity.value = ''
  searchCounty.value = ''
  searchCategory.value = ''
  priceMin.value = ''
  priceMax.value = ''
  searchPage.value = '1'
  jumpPage.value = 1
  sortKey.value = ''
  sortDir.value = 'asc'
  sortDir.value = 'asc'
  searchResult.value = {}
}

function highlightKeyword(text) {
  if (!text || !searchKeyword.value.trim()) return text
  const kw = searchKeyword.value.trim()
  const regex = new RegExp(`(${kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  return String(text).replace(regex, '<span class="breed-match">$1</span>')
}

function fmtCell(v) {
  if (v === null || v === undefined || v === '') return '--'
  const n = Number(v)
  if (isNaN(n)) return v
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// Price highlight
function getPriceClass(price, avgPrice) {
  if (price === null || price === undefined || price === '' || String(price).trim() === '') return 'no-price'
  const n = Number(price)
  if (isNaN(n) || !avgPrice) return ''
  if (n > avgPrice * 1.5) return 'price-high'
  if (n < avgPrice * 0.5) return 'price-low'
  return ''
}

function getPriceBadge(item) {
  const n = Number(item.price)
  const av = Number(item.avg_price)
  if (isNaN(n) || !av) return null
  if (n > av * 2) return { text: '异常高', cls: 'badge-danger' }
  if (n > av * 1.5) return { text: '偏高', cls: 'badge-warning' }
  if (n < av * 0.5) return { text: '异常低', cls: 'badge-blue' }
  return null
}

function getTaxDiffBadge(item) {
  const p = Number(item.price)
  const tp = Number(item.tax_price)
  if (isNaN(p) || isNaN(tp) || p <= 0) return null
  const diff = (tp - p) / p
  if (diff > 0.2) return '含税溢价 ' + (diff * 100).toFixed(0) + '%'
  return null
}

function getPriceChange(item) {
  const n = Number(item.price)
  const prev = Number(item.prev_price)
  if (isNaN(n) || isNaN(prev) || prev <= 0) return null
  const pct = ((n - prev) / prev) * 100
  const sign = pct >= 0 ? '+' : ''
  const arrow = pct >= 0 ? '↑' : '↓'
  return {
    text: `${sign}${pct.toFixed(1)}%`,
    cls: pct >= 0 ? 'change-up' : 'change-down'
  }
}

function getCellClass(key, item) {
  if (key === 'price') return 'price-cell ' + getPriceClass(item.price, item.avg_price)
  if (key === 'tax_price') return 'tax-price-cell'
  if (key === 'unit') return 'unit-cell'
  if (key === 'date') return 'date-cell'
  if (key === 'spec') return 'td-spec'
  if (key === 'province') return 'td-province'
  if (key === 'city') return 'td-city'
  if (key === 'county') return 'td-county'
  return ''
}

function isStale(dateStr) {
  if (!dateStr) return false
  const d = new Date(dateStr)
  const now = new Date()
  const diff = (now - d) / (1000 * 60 * 60 * 24)
  return diff > 30
}

function staleText(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now - d) / (1000 * 60 * 60 * 24))
  if (diff > 60) return `🕐 ${Math.floor(diff / 30)}个月前`
  if (diff > 30) return `🕐 ${diff}天前`
  return ''
}

function onKeywordInput() {
  if (debounceTimer.value) clearTimeout(debounceTimer.value)
  debounceTimer.value = setTimeout(() => doSearch(), 300)
}

function clearHistory() {
  searchHistory.value = []
  window.localStorage.removeItem('gov_price_history')
}

function isPresetActive(preset) {
  return priceMin.value === preset.min && priceMax.value === preset.max
}

function applyPreset(preset) {
  priceMin.value = preset.min
  priceMax.value = preset.max
  doSearch()
}

function expandRange() {
  priceMin.value = ''
  priceMax.value = ''
}

function toggleColConfig() {
  showColConfig.value = !showColConfig.value
}

function exportCurrentPage() {
  const headers = visibleColumns.value.map(c => c.label).join(',')
  const rows = sortedData.value.map(item =>
    visibleColumns.value.map(c => {
      const val = item[c.key]
      return typeof val === 'string' && val.includes(',') ? `"${val}"` : (val ?? '')
    }).join(',')
  ).join('\n')
  const csv = '\uFEFF' + headers + '\n' + rows
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `建材价格_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

async function refreshAll() {
  await Promise.all([loadOverview(), loadCityOptions()])
  if (searchKeyword.value || searchProvince.value || searchCity.value || searchCounty.value || priceMin.value || priceMax.value) {
    await doSearch()
  }
  showToast('数据已刷新')
}

function showToast(msg) {
  toast.value = { show: true, msg }
  setTimeout(() => { toast.value.show = false }, 3000)
}

// Close column config on outside click
function handleDocClick(e) {
  if (colConfigRef.value && !colConfigRef.value.contains(e.target)) {
    showColConfig.value = false
  }
}

// Reload overview (with current search filters) when filter state changes
watch(
  [searchKeyword, searchProvince, searchCity, priceMin, priceMax],
  async () => {
    if (Object.keys(searchResult.value).length) {
      await loadOverview()
    }
  }
)

// ============================================================
// API
// ============================================================
async function loadAPI(url) {
  try { return (await axios.get(url)).data } catch { return {} }
}

async function loadOverview() {
  // 不传搜索过滤条件，获取总览全量数据
  const d = await loadAPI(`${API}/stats/overview`)
  overview.value = d || { total_docs: 0, total_provinces: 0, total_cities: 0, avg_price: 0, by_province: [] }
}

async function loadCityOptions() {
  const d = await loadAPI(`${API}/filter-options`)
  if (d) {
    cityOptions.value = d.cities || []
    countyOptions.value = d.counties || []
    provinceCityMap.value = d.provinceCityMap || {}
  }
}

async function loadCategoryOptions() {
  const d = await loadAPI(`${API}/stats/overview`)
  if (d?.by_category) {
    categoryOptions.value = d.by_category.map(c => ({ key: c.category, count: c.count }))
  }
}

async function onMount() {
  await Promise.all([loadOverview(), loadCityOptions(), loadCategoryOptions(), doSearch()])
}

onMounted(() => {
  document.addEventListener('click', handleDocClick)
})

onMounted(onMount)

// Keyboard shortcuts
onMounted(() => {
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      showColConfig.value = false
    }
    if ((e.key === '/' || (e.ctrlKey && e.key === 'k')) && !e.target.matches('input, textarea')) {
      e.preventDefault()
      document.querySelector('.filter-input')?.focus()
    }
  })
})

// ============================================================
</script>
