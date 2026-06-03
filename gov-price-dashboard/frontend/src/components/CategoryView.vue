<template>
  <div class="cat-page">
    <!-- Page header -->
    <div class="cat-header">
      <div class="cat-title">产品类别分析</div>
      <div class="cat-subtitle">共 <strong>{{ totalDocs.toLocaleString() }}</strong> 条数据，<strong>{{ catCount }}</strong> 个产品类别｜<strong>{{ topCategory?.key }}</strong> 占比最高（<strong>{{ topCategoryPct }}</strong>%）｜覆盖 <strong>{{ overview.total_provinces }}</strong> 省/<strong>{{ overview.total_cities }}</strong> 城</div>
    </div>

    <!-- Category grid -->
    <div class="cat-grid" v-if="!selectedCategory">
      <div
        v-for="cat in categories"
        :key="cat.key"
        class="cat-card"
        :style="{ '--accent': getCategoryColor(cat.key) }"
        @click="selectCategory(cat)"
      >
        <div class="cat-card-inner">
          <div class="cat-name">{{ cat.key }}</div>
          <div class="cat-emoji">{{ getCategoryEmoji(cat.key) }}</div>
          <div class="cat-count">{{ cat.count.toLocaleString() }}</div>
          <div class="cat-pct">{{ getPercent(cat.count) }}%</div>
          <div class="cat-bar-wrap">
            <div class="cat-bar" :style="{ width: getPercent(cat.count) + '%' }"></div>
          </div>
          <div class="cat-province-preview" v-if="cat.top_provinces && cat.top_provinces.length">
            <span class="province-chip" v-for="p in cat.top_provinces.slice(0,3)" :key="p.key">
              {{ p.key }} {{ p.count }}
            </span>
          </div>
        </div>
      </div>
    </div>


    <!-- Detail view -->
    <div v-if="selectedCategory" class="cat-detail">
      <div class="cat-detail-header">
        <button class="btn-back" @click="goBack">← 返回</button>
        <div class="cat-detail-title">
          {{ selectedCategory.key }}
          <span class="detail-count">({{ selectedCategory.count?.toLocaleString() }} 条)</span>
        </div>
      </div>

      <!-- Breed table -->
      <div class="detail-section">
        <div class="section-title">品种列表 ({{ distinctBreedCount }})</div>
        <div class="breed-table">
          <!-- Breed list (grid layout: name + count) -->
          <div class="breed-name-grid">
            <div
              class="breed-grid-item"
              :class="{ active: expandedBreed === b.key }"
              v-for="(b, idx) in displayedBreeds"
              :key="b.key"
              @click="toggleBreed(b)"
            >
              <span class="breed-grid-name">{{ b.key }}</span>
              <span class="breed-grid-count">{{ b.count.toLocaleString() }}</span>
            </div>
          </div>
          <!-- Breed detail expand panel -->
          <div v-if="expandedBreed" class="breed-detail-panel">
            <div class="breed-detail-header">
              <div class="breed-detail-title">
                <span>📦 {{ expandedBreed }}</span>
                <span class="breed-detail-sub">规格价格分析｜共 {{ breedDetail.total_records?.toLocaleString() }} 条记录</span>
              </div>
              <button class="btn-back" @click.stop="expandedBreed = null">✕ 关闭</button>
            </div>
            <!-- Unit tabs -->
            <div class="unit-tabs" v-if="breedDetail.units?.length > 1">
              <button
                v-for="u in breedDetail.units"
                :key="u.key"
                class="unit-tab"
                :class="{ active: selectedUnit === u.key }"
                @click="selectedUnit = u.key"
              >{{ u.key }} <span class="unit-tab-count">({{ u.count.toLocaleString() }})</span></button>
            </div>
            <!-- Spec table: pagination sticky at top inside scrollable container -->
            <div v-if="currentUnitData" class="spec-body">
              <div class="spec-debug" style="display:none">currentUnitData={{ currentUnitData?.specs?.length }} pagedSpecs={{ pagedSpecs.length }} selectedUnit={{ selectedUnit }} currentSpecTotal={{ currentSpecTotal }}</div>
              <div class="spec-table-wrap">
                <div class="spec-pagination" v-if="currentSpecTotal > pagedSpecs.length">
                  <button class="page-btn" @click="loadBreedDetail(selectedCategory.key, expandedBreed, breedPage - 1)" :disabled="breedPage <= 1">上一页</button>
                  <span class="page-info">{{ breedPage }}/{{ Math.ceil((currentSpecTotal || 0) / (breedPageSize.value || 1)) }}</span>
                  <button class="page-btn" @click="loadBreedDetail(selectedCategory.key, expandedBreed, breedPage + 1)" :disabled="breedPage >= Math.ceil((currentSpecTotal || 0) / (breedPageSize.value || 1))">下一页</button>
                </div>
                <div class="spec-table-header">
                  <span class="spec-th">规格</span>
                  <span class="spec-th">省份</span>
                  <span class="spec-th">条数</span>
                  <span class="spec-th">均价</span>
                  <span class="spec-th">最低</span>
                  <span class="spec-th">最高</span>
                </div>
                <div
                  v-for="(sp, si) in pagedSpecs"
                  :key="sp.key + si"
                  class="spec-row"
                  :class="{ striped: si % 2 === 1 }"
                >
                  <span class="spec-td spec-key" :title="sp.key">{{ sp.key === '/' ? '—' : sp.key }}</span>
                  <span class="spec-td">{{ sp.province || '—' }}</span>
                  <span class="spec-td">{{ sp.count.toLocaleString() }}</span>
                  <span class="spec-td price">{{ fmtPrice(sp.avg_price) }}</span>
                  <span class="spec-td price-low">{{ fmtPrice(sp.min_price) }}</span>
                  <span class="spec-td price-high">{{ fmtPrice(sp.max_price) }}</span>
                </div>
                <div v-if="breedDetail.loading" class="spec-loading">加载中...</div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="showAllBreeds && breedsMoreLoading" class="cat-list-loading">加载中...</div>
        <div v-if="showAllBreeds && hasMoreBreeds" class="cat-list-pagination">
          <button class="page-btn" @click="loadMoreBreeds" :disabled="breedsMoreLoading">加载更多 ({{ displayedBreeds.length }}/{{ distinctBreedCount }})</button>
        </div>
      </div>
    </div>

    <div v-if="loading" class="cat-loading">
      <div class="spinner"></div>
      <span>加载中...</span>
    </div>
    <div v-if="error" class="cat-error">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch, computed, onUnmounted } from 'vue'
import axios from 'axios'
import { markRaw } from 'vue'
import * as echarts from 'echarts'

const API = import.meta.env.VITE_API_URL || '/api'
const loading = ref(false)
const error = ref('')
const categories = ref([])
const totalDocs = ref(0)
const overview = ref({ total_provinces: 0, total_cities: 0, avg_price: 0 })

const topCategory = computed(() => categories.value[0] || null)
const topCategoryPct = computed(() => {
  if (!totalDocs.value || !topCategory.value) return '0'
  return (topCategory.value.count / totalDocs.value * 100).toFixed(1)
})
const catCount = computed(() => categories.value.length)
const selectedCategory = ref(null)
const priceChartIns = ref(null)
const categoryProducts = ref([])
const productPage = ref(1)
const productPages = ref(1)
const productTotal = ref(0)
const productPageSize = ref(20)
const jumpProductPage = ref(1)
const loadingProducts = ref(false)
const showAllBreeds = ref(false)
const breedsMoreLoading = ref(false)
const breedsPage = ref(1)
const breedsPageSize = ref(50)
const allBreedsList = ref([])
const expandedBreed = ref(null)
const breedDetail = ref({ units: [], total_records: 0, loading: false })
const selectedUnit = ref('')
const breedPage = ref(1)
const breedPageSize = ref(50)
// 分页数据独立存储，只在切换品种/unit 时清空，页码切换时追加
const pagedSpecs = ref([])
// 当前 unit 的总规格数（不受分页替换影响）
const currentSpecTotal = ref(0)

const currentUnitData = computed(() => {
  if (!breedDetail.value.units?.length) return null
  return breedDetail.value.units.find(u => u.key === selectedUnit.value) || breedDetail.value.units[0]
})

// 品种展开时重置页码和单位
watch(expandedBreed, async (val) => {
  if (!val) return
  breedPage.value = 1
  selectedUnit.value = ''
  pagedSpecs.value = []
  currentSpecTotal.value = 0
})

// 切换单位 tab 时重新加载规格列表（避免重复请求，手动切换时才触发）
watch(selectedUnit, (newVal, oldVal) => {
  if (!newVal || newVal === oldVal) return
  breedPage.value = 1
  pagedSpecs.value = []
  currentSpecTotal.value = 0
  loadBreedDetail(selectedCategory.value.key, expandedBreed.value, 1)
})

const distinctBreedCount = computed(() => selectedCategory.value?.breed_count || selectedCategory.value?.breeds?.length || 0)
const hasMoreBreeds = computed(() => displayedBreeds.value.length < distinctBreedCount.value)

const displayedBreeds = computed(() => {
  if (!showAllBreeds.value) {
    return selectedCategory.value?.breeds?.slice(0, 20) || []
  }
  return allBreedsList.value
})

const PROVINCE_COLORS = [
  '#4a90d9','#50c5a8','#f5a623','#e85555','#9b59b6',
  '#34495e','#e67e22','#1abc9c','#3498db','#95a5a6',
  '#e74c3c','#2ecc71','#f39c12','#c0392b','#7f8c8d',
  '#8e44ad','#16a085','#d35400','#cf5c2a','#e11d48',
]

const CATEGORY_EMOJI = {
  '给排水材料':'🚿','电气材料':'⚡','市政工程材料':'🏗️','砌体墙体材料':'🧱',
  '钢材金属材料':'🔩','园林绿化':'🌿','板材吊顶隔墙材料':'🪚','防水密封材料':'☂️',
  '混凝土预制构件':'🏭','水泥胶凝材料':'🧱','安装辅材':'⚙️','玻璃采光材料':'🔮',
  '消防材料':'🔥','门窗幕墙制品':'🚪','砂石骨料':'🪨','涂料饰面材料':'🎨',
  '保温隔热材料':'❄️','其他':'📦','五金配件':'🔧','弱电智能化材料':'📡',
  '防火材料':'🛡️','金属构件':'⚙️','土工材料':'🕸️','暖通材料':'🌡️',
  '仪器仪表':'⚖️',
}

function getCategoryEmoji(name) {
  return CATEGORY_EMOJI[name] || '📦'
}

function getCategoryColor(name) {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  const hue = Math.abs(hash % 360)
  return `hsl(${hue}, 55%, 48%)`
}

function getCategoryIconStyle(name) {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  // 1536x1024 sprite, 24 cols x 16 rows, 64x64 per icon
  const col = Math.abs(hash) % 24
  const row = Math.abs(hash >> 4) % 16
  const x = 28 + col * 64
  const y = 22 + row * 64
  return {
    backgroundImage: `url(/img/icons.jpg)`,
    backgroundSize: '1536px 1024px',
    backgroundPosition: `-${x}px -${y}px`,
  }
}

function getProvColor(idx) {
  return PROVINCE_COLORS[idx % PROVINCE_COLORS.length]
}

function getPercent(count) {
  if (!totalDocs.value) return '0'
  return (count / totalDocs.value * 100).toFixed(1)
}

function getProvPercent(count) {
  if (!selectedCategory.value?.count) return 0
  return count / selectedCategory.value.count * 100
}

async function loadCategories() {
  loading.value = true
  error.value = ''
  try {
    const [catRes, countRes] = await Promise.all([
      axios.get(`${API}/stats/categories`, { params: { size: 100 } }),
      axios.get(`${API}/stats/overview`),
    ])
    categories.value = catRes.data?.data || []
    totalDocs.value = countRes.data?.total_docs || 0
    if (countRes.data) {
      overview.value = {
        total_provinces: countRes.data.total_provinces || 0,
        total_cities: countRes.data.total_cities || 0,
        avg_price: countRes.data.avg_price || 0,
      }
    }

    // Load top provinces for each category
    const provPromises = categories.value.map(cat =>
      axios.get(`${API}/stats/category-detail`, { params: { category: cat.key } })
        .then(r => ({ key: cat.key, data: r.data?.data || {} }))
        .catch(() => null)
    )
    const provResults = await Promise.all(provPromises)
    provResults.forEach(result => {
      if (!result) return
      const cat = categories.value.find(c => c.key === result.key)
      if (cat) {
        cat.top_provinces = result.data.provinces?.slice(0, 5) || []
      }
    })
  } catch (e) {
    error.value = '加载失败：' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

async function selectCategory(cat) {
  selectedCategory.value = { ...cat, provinces: [], breeds: [], avg_price: 0, max_price: 0, province_count: 0 }
  productPage.value = 1
  loading.value = true
  try {
    const [detailRes, priceRes] = await Promise.all([
      axios.get(`${API}/stats/category-detail`, { params: { category: cat.key } }),
      axios.get(`${API}/stats/category-price-ranges`, { params: { category: cat.key } }),
    ])
    const detail = detailRes.data?.data || {}
    selectedCategory.value.provinces = detail.provinces || []
    selectedCategory.value.breeds = detail.breeds || []
    selectedCategory.value.breed_count = detail.breed_count || 0
    selectedCategory.value.avg_price = detail.avg_price || 0
    selectedCategory.value.max_price = detail.max_price || 0
    selectedCategory.value.province_count = selectedCategory.value.provinces.length

    await nextTick()
    renderPriceChart(priceRes.data?.data || [], priceRes.data?.stats)
    await loadCategoryProducts()
  } catch (e) {
    error.value = '加载详情失败：' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

async function loadCategoryProducts() {
  if (!selectedCategory.value) return
  loadingProducts.value = true
  try {
    const res = await axios.get(`${API}/search`, {
      params: {
        category: selectedCategory.value.key,
        page: productPage.value,
        page_size: productPageSize.value,
      }
    })
    const data = res.data?.data || []
    categoryProducts.value = data
    productTotal.value = res.data?.total || 0
    productPages.value = res.data?.pages || 1
  } catch (e) {
    categoryProducts.value = []
  } finally {
    loadingProducts.value = false
  }
}

function prevProductPage() {
  if (productPage.value > 1) {
    productPage.value--
    loadCategoryProducts()
  }
}

function nextProductPage() {
  if (productPage.value < productPages.value) {
    productPage.value++
    loadCategoryProducts()
  }
}

function goProductPage(p) {
  productPage.value = p
  loadCategoryProducts()
}

function fmtPrice(v) {
  if (v == null || v === '') return '—'
  return '¥' + Number(v).toFixed(2)
}

function goBack() {
  showAllBreeds.value = false
  allBreedsList.value = []
  breedsPage.value = 1
  expandedBreed.value = null
  selectedCategory.value = null
}

function toggleShowBreeds() {
  if (showAllBreeds.value) {
    showAllBreeds.value = false
  } else {
    showAllBreeds.value = true
    if (allBreedsList.value.length === 0) {
      loadMoreBreeds()
    }
  }
}

async function loadMoreBreeds() {
  if (!selectedCategory.value) return
  breedsMoreLoading.value = true
  try {
    const res = await axios.get(`${API}/stats/category-breeds`, {
      params: {
        category: selectedCategory.value.key,
        page: breedsPage.value,
        page_size: breedsPageSize.value,
      }
    })
    const data = res.data?.data || []
    if (breedsPage.value === 1) {
      allBreedsList.value = data
    } else {
      allBreedsList.value.push(...data)
    }
    // 任何有数据的响应都推进页码，防止最后一页不满时按钮仍可点击导致重复请求
    if (data.length > 0) {
      breedsPage.value++
    }
  } catch (e) {
    console.error('加载品种失败', e)
  } finally {
    breedsMoreLoading.value = false
  }
}

async function loadBreedDetail(category, breed, page = 1) {
  console.log('loadBreedDetail CALLED:', { category, breed, page })
  breedDetail.value.loading = true
  try {
    const res = await axios.get(`${API}/stats/breed-detail`, {
      params: { category, breed, page, page_size: breedPageSize.value }
    })
    const d = res.data?.data
    console.log('loadBreedDetail resp:', JSON.stringify(d).slice(0,300))
    if (!d) { console.warn('loadBreedDetail: no data'); return }
    if (!d.units?.length) { console.warn('loadBreedDetail: no units'); return }
    // 始终更新 units（品种只有一个单位时也需要写入）
    breedDetail.value.units = d.units
    console.log('set breedDetail.value.units, length:', d.units.length)
    // 选中的单位
    const targetUnit = selectedUnit.value
      ? (d.units.find(u => u.key === selectedUnit.value) || d.units[0])
      : d.units[0]
    if (!selectedUnit.value) {
      selectedUnit.value = targetUnit.key
      console.log('set selectedUnit to:', selectedUnit.value)
    }
    console.log('targetUnit:', targetUnit.key, 'specs.length:', targetUnit.specs?.length)
    const newSpecs = targetUnit.specs || []
    const newTotal = targetUnit.spec_total || 0
    pagedSpecs.value = newSpecs
    currentSpecTotal.value = newTotal
    breedDetail.value.total_records = d.total_records ?? breedDetail.value.total_records
    console.log('final pagedSpecs:', pagedSpecs.value.length, 'currentSpecTotal:', currentSpecTotal.value, 'expandedBreed:', expandedBreed.value)
    breedPage.value = page
  } catch (e) {
    console.error('加载品种详情失败', e)
  } finally {
    breedDetail.value.loading = false
  }
}

async function toggleBreed(b) {
  if (expandedBreed.value === b.key) {
    expandedBreed.value = null
    return
  }
  expandedBreed.value = b.key
  selectedUnit.value = ''
  breedPage.value = 1
  await loadBreedDetail(selectedCategory.value.key, b.key, 1)
}

function getPriceChange(item) {
  if (!item.prev_price || !item.price) return null
  const diff = item.price - item.prev_price
  if (Math.abs(diff) < 0.01) return null
  const pct = (diff / item.prev_price) * 100
  return {
    text: (diff > 0 ? '+' : '-') + Math.abs(pct).toFixed(1) + '%',
    cls: diff > 0 ? 'change-up' : 'change-down',
  }
}

function onProductPageSizeChange() {
  productPage.value = 1
  loadCategoryProducts()
}

const productPageRange = computed(() => {
  const total = productPages.value
  const cur = productPage.value
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const pages = []
  pages.push(1)
  if (cur > 3) pages.push('...')
  for (let i = Math.max(2, cur - 1); i <= Math.min(total - 1, cur + 1); i++) pages.push(i)
  if (cur < total - 2) pages.push('...')
  pages.push(total)
  return pages
})

function renderPriceChart(ranges, stats) {
  const el = document.getElementById('catPriceChart')
  if (!el || !ranges.length) return
  if (priceChartIns.value) { priceChartIns.value.dispose(); priceChartIns.value = null }

  const chart = markRaw(echarts.init(el))
  priceChartIns.value = chart

  const colors = ['#6dd5ed','#4facfe','#6a85f5','#9b59b6','#a78bfa','#f59e0b','#f97316','#ef4444','#e11d48','#06b6d4','#84cc16']

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1a2332',
      borderColor: '#1e3a5f',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: params => {
        const p = params[0]
        return `<b>${p.name}</b><br/>数量: <b style="color:#3b9eff">${p.value.toLocaleString()}</b>`
      }
    },
    grid: { left: '3%', right: '4%', bottom: '12%', top: '8%', containLabel: true },
    xAxis: {
      type: 'category',
      data: ranges.map(r => r.range),
      axisLabel: { color: '#94a3b8', fontSize: 10, rotate: 30, interval: 0 },
      axisLine: { lineStyle: { color: '#1e3a5f' } },
      axisTick: { show: false }
    },
    yAxis: {
      name: '产品数量',
      nameTextStyle: { color: '#64748b', fontSize: 10 },
      type: 'value',
      axisLabel: { color: '#64748b', fontSize: 10 },
      splitLine: { lineStyle: { color: '#1e3a5f', type: 'dashed' } }
    },
    series: [{
      type: 'bar',
      data: ranges.map((r, i) => ({ value: r.count, itemStyle: { color: colors[i % colors.length] } })),
      barMaxWidth: 50,
      label: {
        show: true, position: 'top',
        color: '#94a3b8', fontSize: 9,
        formatter: p => p.value >= 1000 ? (p.value/1000).toFixed(0)+'k' : p.value
      }
    }],
  }, true)

  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
  }
  resizeHandler = () => chart.resize()
  window.addEventListener('resize', resizeHandler)
}

let resizeHandler = null

onUnmounted(() => {
  if (priceChartIns.value) {
    priceChartIns.value.dispose()
    priceChartIns.value = null
  }
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
    resizeHandler = null
  }
  selectedCategory.value = null
})

onMounted(() => loadCategories())
</script>

<style scoped>
.cat-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 20px;
  min-height: 100vh;
  background: linear-gradient(180deg, #0c1222 0%, #111827 100%);
  box-sizing: border-box;
  padding-top: 16px;
}

.cat-header {
  background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f172a 100%);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 16px 20px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}

.cat-title {
  font-size: 18px;
  font-weight: 700;
  color: #f1f5f9;
  text-shadow: 0 2px 12px rgba(56,189,248,0.2);
}

.cat-subtitle {
  font-size: 13px;
  color: #64748b;
  margin-top: 4px;
}

.cat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.cat-card {
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 8px 32px rgba(0,0,0,0.25);
  position: relative;
  overflow: hidden;
}

.cat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  background: var(--accent, #38bdf8);
}

.cat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 40px rgba(0,0,0,0.35);
  border-color: rgba(56,189,248,0.3);
}

.cat-emoji {
  font-size: 22px;
  position: absolute;
  top: 12px;
  right: 12px;
  line-height: 1;
  z-index: 1;
  filter: drop-shadow(0 2px 8px rgba(0,0,0,0.3));
}


.cat-card-inner {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 56px;
}

.cat-name {
  font-size: 14px;
  font-weight: 700;
  color: #f1f5f9;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
  text-shadow: 0 2px 12px rgba(56,189,248,0.2);
}

.cat-count {
  font-size: 22px;
  font-weight: 700;
  color: #38bdf8;
  line-height: 1.2;
}

.cat-pct {
  font-size: 12px;
  color: #64748b;
  margin-top: -2px;
}

.cat-bar-wrap {
  height: 4px;
  background: rgba(255,255,255,0.06);
  border-radius: 2px;
  margin-top: 6px;
  overflow: hidden;
}

.cat-bar {
  height: 100%;
  background: #38bdf8;
  border-radius: 2px;
  transition: width 0.4s ease;
}

.cat-province-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}

.province-chip {
  font-size: 11px;
  padding: 1px 6px;
  background: rgba(56,189,248,0.1);
  color: #38bdf8;
  border-radius: 3px;
}

/* Detail view */
.cat-detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}

.btn-back {
  padding: 8px 18px;
  background: rgba(30,41,59,0.8);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: #94a3b8;
  transition: background 0.2s, border-color 0.2s;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
}

.btn-back:hover {
  background: rgba(56,189,248,0.1);
  border-color: rgba(56,189,248,0.3);
  color: #38bdf8;
}

.cat-detail-title {
  font-size: 18px;
  font-weight: 700;
  color: #f1f5f9;
  display: flex;
  align-items: center;
  gap: 8px;
}

.detail-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  display: inline-block;
}

.detail-count {
  font-size: 13px;
  font-weight: 400;
  color: #64748b;
}

.detail-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-card {
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px;
  padding: 16px;
  text-align: center;
  box-shadow: 0 8px 32px rgba(0,0,0,0.25);
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #38bdf8;
}

.stat-label {
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
}

.detail-section {
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.25);
  margin-bottom: 16px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #94a3b8;
  margin-bottom: 12px;
}

.province-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 300px;
  overflow-y: auto;
}

.province-bar-row {
  display: grid;
  grid-template-columns: 100px 1fr 50px;
  align-items: center;
  gap: 10px;
}

.province-label {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.province-name {
  font-size: 12px;
  color: #e2e8f0;
  font-weight: 500;
}

.province-count {
  font-size: 11px;
  color: #64748b;
}

.province-bar-track {
  height: 8px;
  background: rgba(255,255,255,0.06);
  border-radius: 4px;
  overflow: hidden;
}

.province-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s ease;
}

.province-pct {
  font-size: 11px;
  color: #64748b;
  text-align: right;
}

.breed-table {
  font-size: 12px;
  border-collapse: collapse;
  width: 100%;
}

.breed-thead {
  display: grid;
  grid-template-columns: 40px 1fr 120px 50px 60px 70px 70px 70px 70px 60px;
  gap: 8px;
  padding: 8px 10px;
  background: rgba(26,35,50,0.8);
  border-radius: 6px;
  margin-bottom: 4px;
}

.breed-th {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
}

.breed-row {
  display: grid;
  grid-template-columns: 40px 1fr 120px 50px 60px 70px 70px 70px 70px 60px;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  align-items: center;
}

.breed-row.striped {
  background: rgba(26,35,50,0.4);
}

.breed-td {
  color: #e2e8f0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.breed-td.rank {
  font-weight: 700;
  color: #64748b;
  text-align: center;
}

.breed-td.breed-name {
  font-weight: 500;
  color: #38bdf8;
}

.breed-td.spec, .breed-td.spec {
  color: #94a3b8;
  font-size: 11px;
}

.breed-td.unit-tag {
  color: #a78bfa;
  font-size: 11px;
  font-weight: 700;
  background: rgba(167,139,250,0.12);
  border: 1px solid rgba(167,139,250,0.3);
  border-radius: 4px;
  padding: 1px 6px;
  text-align: center;
  white-space: nowrap;
}

.breed-td.province {
  color: #64748b;
}

.breed-td.price {
  font-weight: 600;
  color: #34d399;
}

.breed-td.price-low {
  font-weight: 600;
  color: #f87171;
}

.breed-td.price-high {
  font-weight: 600;
  color: #38bdf8;
}

.breed-td.range {
  color: #a78bfa;
  font-size: 11px;
}

.breed-td.count {
  color: #64748b;
}

/* Product list table */
.cat-list-table-wrap {
  overflow-x: auto;
  border-radius: 8px;
}

.spec-cell { color: #64748b !important; }
.text-2-cell { color: #64748b !important; }

.cat-list-loading {
  text-align: center;
  padding: 12px;
  color: #64748b;
  font-size: 12px;
}

.cat-list-pagination {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 12px;
  justify-content: center;
}

.page-info {
  font-size: 11px;
  color: #64748b;
  margin-left: 8px;
  white-space: nowrap;
}

.cat-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px;
  color: #64748b;
  font-size: 14px;
}

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255,255,255,0.1);
  border-top-color: #38bdf8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.cat-error {
  padding: 16px;
  background: rgba(248,113,113,0.1);
  border: 1px solid rgba(248,113,113,0.3);
  border-radius: 8px;
  color: #f87171;
  font-size: 13px;
}

.btn-show-breeds {
  padding: 4px 12px;
  background: rgba(56,189,248,0.1);
  border: 1px solid rgba(56,189,248,0.3);
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
  color: #38bdf8;
  transition: all 0.2s;
}

.btn-show-breeds:hover,
.btn-show-breeds.active {
  background: rgba(56,189,248,0.2);
  border-color: rgba(56,189,248,0.5);
}

/* Breed detail expand panel */
.breed-detail-panel {
  background: rgba(15,23,42,0.6);
  border: 1px solid rgba(56,189,248,0.2);
  border-radius: 6px;
  margin: 4px 0;
  overflow-y: auto;
  max-height: 80vh;
}

.breed-detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: rgba(56,189,248,0.06);
  border-bottom: 1px solid rgba(255,255,255,0.06);
}

.breed-detail-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.breed-detail-title > span:first-child {
  font-size: 14px;
  font-weight: 600;
  color: #38bdf8;
}

.breed-detail-sub {
  font-size: 11px;
  color: #94a3b8;
}

.breed-detail-header > .btn-back {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  color: #94a3b8;
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.breed-detail-header > .btn-back:hover {
  background: rgba(248,113,113,0.12);
  border-color: rgba(248,113,113,0.3);
  color: #f87171;
}

/* Unit tabs */
.unit-tabs {
  display: flex;
  gap: 8px;
  padding: 6px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  flex-wrap: wrap;
}

.unit-tab {
  padding: 4px 12px;
  border-radius: 20px;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04);
  color: #94a3b8;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.unit-tab:hover {
  border-color: rgba(56,189,248,0.4);
  color: #38bdf8;
}

.unit-tab.active {
  background: rgba(56,189,248,0.15);
  border-color: rgba(56,189,248,0.5);
  color: #38bdf8;
  font-weight: 600;
}

.unit-tab-count {
  font-size: 10px;
  opacity: 0.7;
}

/* Spec table */
.spec-body {
  display: block;
  max-height: calc(100vh - 240px);
  overflow-y: auto;
}

.spec-table-wrap {
  display: block;
  overflow-y: auto;
  overflow-x: auto;
}

.spec-table-header,
.spec-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr 1fr 1fr;
  align-items: center;
  flex-shrink: 0;
}

.spec-table-header {
  background: rgba(255,255,255,0.03);
  border-bottom: 1px solid rgba(255,255,255,0.06);
  position: sticky;
  top: 0;
}

.spec-th {
  padding: 5px 10px;
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.spec-row {
  border-bottom: 1px solid rgba(255,255,255,0.03);
  transition: background 0.15s;
}

.spec-row:hover {
  background: rgba(56,189,248,0.04);
}

.spec-row.striped {
  background: rgba(255,255,255,0.015);
}

.spec-td {
  padding: 4px 10px;
  font-size: 12px;
  color: #e2e8f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.spec-key {
  color: #94a3b8;
}

.spec-loading {
  padding: 8px;
  text-align: center;
  color: #64748b;
  font-size: 12px;
}

.spec-empty {
  padding: 12px;
  text-align: center;
  color: #475569;
  font-size: 12px;
}

.spec-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 6px 10px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 10;
}

.page-info {
  font-size: 11px;
  color: #64748b;
}

.page-btn {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04);
  color: #94a3b8;
  transition: all 0.2s;
}

.page-btn:hover:not(:disabled) {
  background: rgba(56,189,248,0.15);
  border-color: rgba(56,189,248,0.4);
  color: #38bdf8;
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Breed row clickable */
.breed-row {
  cursor: pointer;
  transition: background 0.15s;
}

.breed-row:hover {
  background: rgba(56,189,248,0.06);
}

.breed-row.active {
  background: rgba(56,189,248,0.12);
  border-left: 2px solid #38bdf8;
}

/* Simplified breed name list */
.breed-name-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
}

.breed-name-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  border: 1px solid transparent;
}

.breed-name-item:hover {
  background: rgba(56,189,248,0.08);
  border-color: rgba(56,189,248,0.2);
}

.breed-name-item.active {
  background: rgba(56,189,248,0.15);
  border-color: rgba(56,189,248,0.4);
}

.breed-name-text {
  font-size: 13px;
  color: #e2e8f0;
  font-weight: 500;
}

.breed-count-badge {
  font-size: 11px;
  color: #38bdf8;
  background: rgba(56,189,248,0.1);
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid rgba(56,189,248,0.2);
}

.breed-name-item.active .breed-count-badge {
  background: rgba(56,189,248,0.2);
  border-color: rgba(56,189,248,0.4);
}

/* Grid layout for breed list */
.breed-name-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px;
  padding: 8px 0;
}

.breed-grid-item {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 10px 14px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid rgba(255,255,255,0.06);
  background: rgba(255,255,255,0.03);
  min-height: 56px;
}

.breed-grid-item:hover {
  background: rgba(56,189,248,0.08);
  border-color: rgba(56,189,248,0.3);
  transform: translateY(-1px);
}

.breed-grid-item.active {
  background: rgba(56,189,248,0.15);
  border-color: rgba(56,189,248,0.5);
}

.breed-grid-name {
  font-size: 13px;
  font-weight: 500;
  color: #e2e8f0;
  line-height: 1.4;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.breed-grid-count {
  font-size: 11px;
  color: #38bdf8;
}
</style>
