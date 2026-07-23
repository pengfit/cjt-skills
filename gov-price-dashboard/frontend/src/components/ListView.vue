<!--
  列表页 — list tab 视图(2026-07-13 抽自 App.vue, 2026-07-15 Grid 化 + 内容感知列宽)
  - 模板来自原 App.vue `<template v-if="currentTab === 'list'">` 整块
  - state / computed / actions 全部委托给 useListSearch composable
  - 跨 tab 依赖(loadOverview)由 App.vue 通过 props 注入
  - 表格部分从原生 <table> 改为 CSS Grid + subgrid (2026-07-15)
  - 列宽按内容自适应：5 列都用 minmax(min, max-content)，但 max-content 在整列跨所有行求最大值
-->
<template>
  <!-- Filter Drawer (slide-in from right) -->
  <Transition name="drawer">
    <div class="drawer" v-if="showDrawer">
      <div class="drawer-header">
        <span>更多筛选</span>
        <span class="drawer-close" @click="showDrawer = false" role="button" aria-label="关闭筛选抽屉" tabindex="0">✕</span>
      </div>
      <div class="drawer-body">
        <div class="filter-group">
          <label class="filter-label">省份</label>
          <CustomSelect
            v-model="searchProvince"
            :options="provinceOptions.map(p => ({ key: p.key, count: p.count }))"
            placeholder="全部省份"
            :searchable="true"
            @change="onProvinceChange"
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
            @change="onCityChange"
          />
        </div>
        <div class="filter-group">
          <label class="filter-label">区县</label>
          <CustomSelect
            v-model="searchCounty"
            :options="filteredCounties.map(c => ({ key: c.key, count: c.count }))"
            :disabled="!searchProvince || !searchCity"
            placeholder="全部区县"
            :searchable="true"
          />
        </div>
        <div class="filter-group">
          <label class="filter-label">日期范围</label>
          <div class="date-presets" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px">
            <span
              v-for="preset in datePresets"
              :key="preset.label"
              class="preset-chip"
              :class="{ active: dateRangeKey === preset.key }"
              @click="applyDatePreset(preset)"
            >{{ preset.label }}</span>
            <span
              v-if="dateRangeKey === 'custom'"
              class="preset-chip active"
              @click="dateRangeKey = 'all'"
              title="清除自定义"
            >自定义 ✓</span>
          </div>
          <div class="date-range-row" style="display:flex;align-items:center;gap:6px">
            <input
              class="price-input filter-input"
              type="date"
              v-model="dateFrom"
              :max="dateTo || undefined"
              style="width:130px"
              @change="dateRangeKey = 'custom'"
            />
            <span class="price-dash">-</span>
            <input
              class="price-input filter-input"
              type="date"
              v-model="dateTo"
              :min="dateFrom || undefined"
              style="width:130px"
              @change="dateRangeKey = 'custom'"
            />
          </div>
        </div>
        <div class="filter-group">
          <label class="filter-label">价格区间</label>
          <div class="price-presets">
            <span
              v-for="preset in pricePresets"
              :key="preset.label"
              class="preset-chip"
              :class="{ active: isPresetActive(preset) }"
              @click="isPresetActive(preset) ? expandRange() : applyPreset(preset);"
            >{{ preset.label }}</span>
          </div>
          <div class="price-range-row" style="margin-top:6px">
            <input class="price-input filter-input" v-model="priceMin" placeholder="最低价" @keyup.enter="doSearch()" style="width:78px" />
            <span class="price-dash">-</span>
            <input class="price-input filter-input" v-model="priceMax" placeholder="最高价" @keyup.enter="doSearch()" style="width:78px" />
          </div>
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
            <button class="history-clear-btn" @click="clearHistory()">清空</button>
          </div>
        </div>
      </div>
      <div class="drawer-footer">
        <button class="btn-primary" @click="() => { showDrawer = false; doSearch(); }">🔍 确定</button>
        <button class="btn-ghost" @click="resetSearch">重置</button>
      </div>
    </div>
  </Transition>
  <Transition name="fade">
    <div class="drawer-backdrop" v-if="showDrawer" @click="showDrawer = false"></div>
  </Transition>

    <div class="list-tree-layout">
      <aside class="list-tree-panel" :class="{ collapsed: categoryPanelCollapsed }">
        <button class="panel-toggle" @click="categoryPanelCollapsed = !categoryPanelCollapsed" :title="categoryPanelCollapsed ? '展开分类' : '收起分类'">
          {{ categoryPanelCollapsed ? '▸' : '◂' }}
        </button>
        <div class="panel-inner" v-show="!categoryPanelCollapsed">
          <CategoryTreeSidebar
            :active-l3="searchCategoryCode"
            @select="onCategoryTreeSelect"
          />
        </div>
      </aside>

      <main class="content-area">

      <!-- PageHeader 在 main 内,跨 content-area 全宽(原位恢复) -->
      <PageHeader
        variant="flat"
        title="全部数据"
        subtitle="产品名称 / 多维筛选 / 全城跨期比价 · 数据源 <code>DWS</code> 索引族"
        :stats="[
          { label: '总记录', value: fmt.int(stats.total), title: '当前筛选条件下的总命中条数' },
          { label: '覆盖省份', value: stats.provinces, title: '已有数据的省份数' },
          { label: '当前页', value: stats.current, title: `本页 ${pageSize} 条中的可见条数` },
        ]"
      />

      <div class="list-toolbar-sticky">
        <div class="category-breadcrumb" v-if="categoryBreadcrumb.length">
          <span class="breadcrumb-icon">🏷️</span>
          <template v-for="(part, i) in categoryBreadcrumb" :key="part.code">
            <span v-if="i > 0" class="breadcrumb-sep">›</span>
            <span class="breadcrumb-part" :class="{ active: i === categoryBreadcrumb.length - 1 }">{{ part.name }}</span>
          </template>
        </div>

        <div class="filter-bar filter-bar-inside">
          <input
            class="filter-bar-input"
            v-model="searchKeyword"
            placeholder="🔍 产品名称 / 关键词"
            @keyup.enter="doSearch()"
            @input="onKeywordInput"
          />
          <div class="date-presets-inline">
            <span
              v-for="preset in datePresets"
              :key="preset.key"
              class="preset-chip-inline"
              :class="{ active: dateRangeKey === preset.key }"
              @click="applyDatePreset(preset); doSearch()"
            >{{ preset.label }}</span>
          </div>
          <button class="btn-more" @click="showDrawer = true">更多筛选 ▸</button>
          <button
            class="btn-export"
            :disabled="!sortedData.length"
            :title="sortedData.length ? `导出 ${sortedData.length} 条记录为 CSV(当前筛选)` : '请先加载数据'"
            @click="exportSearchResultCsv"
          >📊 导出 CSV</button>
        </div>

        <div class="filter-tags" v-if="searchKeyword || searchProvince || searchCity || searchCounty || searchCategoryCode || dateFrom || dateTo">
          <span class="filter-tag" v-if="searchKeyword">
            <strong>产品名称</strong>
            <em>{{ searchKeyword }}</em>
            <span class="tag-remove" @click="searchKeyword = ''; doSearch()" role="button" aria-label="清除关键词筛选" tabindex="0">✕</span>
          </span>
          <span class="filter-tag" v-if="searchProvince">
            <strong>省份</strong>
            <em>{{ searchProvince }}</em>
            <span class="tag-remove" @click="searchProvince = ''; searchCity = ''; searchCounty = ''; doSearch()" role="button" aria-label="清除省份筛选" tabindex="0">✕</span>
          </span>
          <span class="filter-tag" v-if="searchCity">
            <strong>城市</strong>
            <em>{{ searchCity }}</em>
            <span class="tag-remove" @click="searchCity = ''; searchCounty = ''; doSearch()" role="button" aria-label="清除城市筛选" tabindex="0">✕</span>
          </span>
          <span class="filter-tag" v-if="searchCategoryCode">
            <strong>{{ {l1:'L1大类',l2:'L2分部',l3:'L3分项'}[searchCategoryLevel] || '分类' }}</strong>
            <em>{{ searchCategoryCode }}</em>
            <span class="tag-remove" @click="searchCategoryCode = ''; searchCategoryLevel = ''; doSearch()" role="button" aria-label="清除分类树筛选" tabindex="0">✕</span>
          </span>
          <span class="filter-tag" v-if="searchCounty">
            <strong>区县</strong>
            <em>{{ searchCounty }}</em>
            <span class="tag-remove" @click="searchCounty = ''; doSearch()" role="button" aria-label="清除区县筛选" tabindex="0">✕</span>
          </span>
          <span class="filter-tag" v-if="dateFrom || dateTo">
            <strong>日期</strong>
            <em>{{ dateFrom || '*' }} → {{ dateTo || '*' }}</em>
            <span class="tag-remove" @click="dateFrom = ''; dateTo = ''; dateRangeKey = 'all'; doSearch()" role="button" aria-label="清除日期筛选" tabindex="0">✕</span>
          </span>
          <span class="filter-tag-clear" @click="resetSearch">清空全部</span>
        </div>
      </div>

        <!-- Skeleton loading (用同一 subgrid 模板) -->
        <div class="content-card skeleton-card" v-if="loading">
          <div class="grid-table skel">
            <div class="grid-header">
              <div
                v-for="col in visibleColumns"
                :key="'h-' + col.key"
                class="grid-cell skel-head"
              >{{ col.label }}</div>
            </div>
            <div class="grid-row skel-grid-row" v-for="i in 8" :key="i">
              <div
                v-for="col in visibleColumns"
                :key="i + '-' + col.key"
                class="grid-cell skel-cell-bar"
              ></div>
            </div>
          </div>
          <div class="skeleton-footer">⏳ 加载中...</div>
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
            可能原因:
            <div>· 该省份暂无此类产品的价格记录</div>
            <div>· 筛选条件过细,请尝试扩大范围</div>
            <div class="empty-suggestions">试试:<span class="suggestion-chip" @click="searchKeyword = ''; doSearch()">清空关键词</span><span class="suggestion-chip" @click="searchCategoryCode = ''; searchCategoryLevel = ''; doSearch()">全部分类</span><span class="suggestion-chip" @click="searchProvince = ''; searchCity = ''; doSearch()">全部省份</span></div>
          </div>
        </div>

        <!-- Data Grid (subgrid 列对齐像素级精准,列宽由内容自适应) -->
        <div class="content-card table-desktop" v-else>
          <div class="grid-scroll">
            <div class="grid-table" :data-cols="visibleColumns.length">
              <!-- Sticky header — 第 1 行 -->
              <div class="grid-header">
                <div
                  v-for="col in visibleColumns"
                  :key="'h-' + col.key"
                  :class="['grid-cell', 'grid-head-cell', 'col-' + col.key, { sorted: sortKey === col.key, sortable: col.sortable }]"
                  @click="col.sortable && sortBy(col.key)"
                >
                  {{ col.label }}
                  <span v-if="col.sortable" class="sort-icon">
                    {{ sortKey === col.key ? (sortDir === 'asc' ? '↑' : '↓') : '↕' }}
                  </span>
                </div>
              </div>

              <!-- Body rows + 展开详情 — 都是 .grid-table 的直接子节点，参与同一 subgrid -->
              <template v-for="(item, idx) in sortedData" :key="item.id || idx">
                <div
                  class="grid-row data-row"
                  :class="{ 'stale-row': isStale(item.date), 'row-expanded': expandedRow === (item.id || idx) }"
                  @click="toggleRow(item, idx)"
                >
                  <div
                    v-for="col in visibleColumns"
                    :key="item.id + '-' + col.key"
                    :class="['grid-cell', 'col-' + col.key, getCellClass(col.key, item)]"
                    :title="col.key === 'breed' ? item.breed : col.key === 'spec' ? item.spec_clean : undefined"
                  >
                    <template v-if="col.key === 'breed'">
                      <div class="breed-cell">
                        <span
                          class="breed-name ctx-breed-link"
                          :title="`${item.breed_clean || item.breed} (点击查看详情)`"
                          @click.stop="openBreedDetail(item)"
                          v-html="highlightKeyword(item.breed)"
                        ></span>
                        <div class="breed-meta">
                          <AttrTags :attr="item.attr" />
                          <span class="meta-sep" v-if="item.city">·</span>
                          <span class="meta-tag city-tag" v-if="item.city">{{ item.city }}</span>
                        </div>
                      </div>
                    </template>
                    <template v-else-if="col.key === 'unit'">{{ item.unit }}</template>
                    <template v-else-if="col.key === 'price'">
                      <div class="price-main">{{ fmtCell(item.price) }}</div>
                      <div class="price-change" v-if="getPriceChange(item)" :class="getPriceChange(item).cls" style="pointer-events:none">{{ getPriceChange(item).text }}</div>
                    </template>
                    <template v-else-if="col.key === 'tax_price'">
                      <div class="price-main" v-if="item.tax_price && Number(item.tax_price) > 0">{{ fmtCell(item.tax_price) }}</div>
                      <div class="price-empty" v-else>—</div>
                    </template>
                    <template v-else-if="col.key === 'attr'">
                      <div class="attr-cell">
                        <AttrTags :attr="item.attr" />
                      </div>
                    </template>
                    <template v-else-if="col.key === 'date'">
                      <span :class="{ 'stale-date': isStale(item.date) }">{{ staleText(item.date) || item.date || '-' }}</span>
                    </template>
                    <template v-else-if="col.key === 'category'">
                      <span class="cat-badge" :title="item.category || ''">{{ item.category || '-' }}</span>
                    </template>
                    <template v-else>{{ item[col.key] ?? '-' }}</template>
                  </div>
                </div>
                <!-- 展开详情行 — 跨满所有列，不是 subgrid（详情面板用内部 auto-fit grid） -->
                <div v-if="expandedRow === (item.id || idx)" class="grid-detail-row" @click.stop>
                  <div class="detail-panel">
                    <div class="detail-panel-grid">
                      <div class="detail-field full-width">
                        <span class="detail-field-label">产品名称</span>
                        <span class="detail-field-value">{{ item.breed }}</span>
                      </div>
                      <div class="detail-field full-width" v-if="item.spec_clean || item.spec">
                        <span class="detail-field-label">规格型号</span>
                        <span class="detail-field-value spec-full">{{ item.spec_clean || item.spec || '-' }}</span>
                      </div>
                      <div class="detail-field full-width" v-if="item.attr && Object.keys(item.attr).length">
                        <span class="detail-field-label">规格属性</span>
                        <span class="detail-field-value"><AttrTags :attr="item.attr" /></span>
                      </div>
                      <div class="detail-field">
                        <span class="detail-field-label">价格</span>
                        <span class="detail-field-value price-em">{{ fmtCell(item.price) }} 元</span>
                      </div>
                      <div class="detail-field" v-if="item.tax_price && Number(item.tax_price) > 0">
                        <span class="detail-field-label">含税价</span>
                        <span class="detail-field-value">{{ fmtCell(item.tax_price) }} 元</span>
                      </div>
                      <div class="detail-field">
                        <span class="detail-field-label">单位</span>
                        <span class="detail-field-value">{{ item.unit || '-' }}</span>
                      </div>
                      <div class="detail-field">
                        <span class="detail-field-label">日期</span>
                        <span class="detail-field-value">{{ item.date || '-' }}</span>
                      </div>
                      <div class="detail-field">
                        <span class="detail-field-label">省份</span>
                        <span class="detail-field-value">{{ item.province || '-' }}</span>
                      </div>
                      <div class="detail-field">
                        <span class="detail-field-label">城市</span>
                        <span class="detail-field-value">{{ item.city || '-' }}</span>
                      </div>
                      <div class="detail-field" v-if="item.county">
                        <span class="detail-field-label">区县</span>
                        <span class="detail-field-value">{{ item.county }}</span>
                      </div>
                      <div class="detail-field" v-if="item.category">
                        <span class="detail-field-label">分类</span>
                        <span class="detail-field-value"><span class="cat-badge">{{ item.category }}</span></span>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- 移动端卡片视图（保留） -->
          <div class="table-mobile">
            <div
              v-for="(item, idx) in sortedData"
              :key="'mob-' + (item.id || idx)"
              class="mobile-card"
              :class="{ 'mobile-card-expanded': expandedRow === (item.id || idx) }"
              @click="toggleRow(item, idx)"
            >
              <div class="mobile-card-main">
                <div class="mobile-card-left">
                  <div class="mobile-card-breed" v-html="highlightKeyword(item.breed)"></div>
                  <div class="mobile-card-spec" v-if="item.spec_clean || item.spec">{{ item.spec_clean || item.spec }}</div>
                  <div class="mobile-card-meta">
                    <span class="mobile-card-cat" v-if="item.category">{{ item.category }}</span>
                    <span class="mobile-card-loc" v-if="item.city">{{ item.province }}{{ item.city }}{{ item.county ? '·' + item.county : '' }}</span>
                  </div>
                </div>
                <div class="mobile-card-right">
                  <div class="mobile-card-price">{{ fmtCell(item.price) }}</div>
                  <div class="mobile-card-tax" v-if="item.tax_price && Number(item.tax_price) > 0">含税 {{ fmtCell(item.tax_price) }}</div>
                  <div class="mobile-card-unit">{{ item.unit || '' }}</div>
                  <div class="mobile-card-date" :class="{ 'stale-date': isStale(item.date) }">{{ staleText(item.date) || item.date || '-' }}</div>
                </div>
              </div>
              <div v-if="expandedRow === (item.id || idx)" class="mobile-card-detail">
                <div class="detail-field full-width" v-if="item.spec_clean || item.spec">
                  <span class="detail-field-label">完整规格</span>
                  <span class="detail-field-value spec-full">{{ item.spec_clean || item.spec }}</span>
                </div>
                <div class="detail-field full-width" v-if="item.attr && Object.keys(item.attr).length">
                  <span class="detail-field-label">属性</span>
                  <span class="detail-field-value"><AttrTags :attr="item.attr" /></span>
                </div>
              </div>
            </div>
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

        <!-- 列配置弹层 -->
        <div v-if="showColConfig" ref="colConfigRef" class="col-config-popover" @click.stop>
          <div class="col-config-title">列显示</div>
          <label v-for="col in allColumns" :key="col.key" class="col-config-row">
            <input type="checkbox" v-model="col.visible" />
            <span>{{ col.label }}</span>
            <span class="col-config-width">{{ col.width }}px</span>
          </label>
          <button class="btn-ghost" @click="toggleColConfig">完成</button>
        </div>

        <!-- Toast 反馈 -->
        <Transition name="fade">
          <div v-if="toast.show" :class="['toast', 'toast-' + toast.type]">{{ toast.msg }}</div>
        </Transition>
      </main>
      </div>
</template>

<script setup>
import { computed, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import AttrTags from './AttrTags.vue'
import CustomSelect from './CustomSelect.vue'
import PageHeader from './PageHeader.vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'

const fmt = useFormatNumber()

const CategoryTreeSidebar = defineAsyncComponent(() => import('./CategoryTreeSidebar.vue'))

const router = useRouter()

// 跨页详情中心 (2026-07-15 A):产品名称点击 → /breed-detail
function openBreedDetail(item) {
  router.push({
    path: '/breed-detail',
    query: {
      breed: item.breed_clean || item.breed || '',
      l3: item.l3 || '',
      province: item.province || '',
      city: item.city || '',
      from: 'list',
    },
  })
}

const props = defineProps({
  bundle: { type: Object, required: true },
  categoryPanelCollapsed: { type: Boolean, default: false },
})

const {
  searchKeyword, searchProvince, searchCity, searchCounty,
  searchCategoryCode, searchCategoryLevel,
  priceMin, priceMax, dateFrom, dateTo, dateRangeKey, datePresets,
  pricePresets, categoryBreadcrumb,
  searchResult, searchPage, jumpPage, pageSize, pageSizeOptions,
  loading, searchError,
  cityOptions, countyOptions, provinceOptions,
  sortKey, sortDir, expandedRow,
  searchHistory, allColumns, showColConfig, showDrawer, colConfigRef,
  toast,
  visibleColumns, filteredCities, filteredCounties, sortedData,
  pageStart, pageEnd, pageRange,
  sortBy, onPageSizeChange, prevPage, nextPage, goToPage,
  onCityChange, onProvinceChange, onCategoryTreeSelect, resetSearch,
  onKeywordInput, isPresetActive, applyPreset, expandRange, clearHistory,
  applyDatePreset, toggleColConfig,
  doSearch, restoreFromQuery, syncToQuery,
  highlightKeyword, fmtCell,
  getPriceChange, getCellClass, isStale, staleText,
  showToast,
  exportSearchResultCsv,
  toggleRow,
  loadCategoryOptions,
} = props.bundle

// 顶部统计（与 taxonomy 页同样的 PageHeader.stats 形态）
const stats = computed(() => ({
  total:     searchResult.value?.total ?? 0,
  provinces: provinceOptions.length,
  current:   sortedData.value?.length ?? 0,
}))

defineExpose({ loadCategoryOptions })
</script>

<style scoped>
/* ===========================================================================
   列表页 CSS Grid + subgrid 表格 (2026-07-15 改造 v2)
   - .grid-table 为根 grid container,定义 grid-template-columns (5 列内容感知)
     max-content 在整列跨 header + 所有 body rows 求最大值 → 列宽严格一致
   - .grid-row / .grid-header 走 subgrid: display:grid + grid-template-columns:subgrid
   - 列下界保护: minmax(min, max-content) — 极少内容(如单位「个」)不塌缩,极多内容自适应
   =========================================================================== */
.table-desktop { padding: 0; }

/* PageHeader 位置与 /taxonomy 对齐 (2026-07-15 P-排错):
   /taxonomy 的 .ctx-page 是 padding: 0 28px 64px（无 top padding）,
   /list 被全局 .content-area 的 `padding: 16px 20px 20px` 推下去 16px。
   补偿方案：margin-top: -16px 让 PageHeader 顶边贴合表格顶部参考线。
   （全局 rules.css 不能动,这里用 scoped 限定仅 /list 生效） */
.page-header {
  margin-top: -16px;
  margin-bottom: 16px;
}
.grid-scroll {
  overflow-x: auto;
  overflow-y: visible;
  max-height: calc(100vh - 320px);
}

/* 根 grid container — 7 列定义 (2026-07-19: 价格拆为不含税/含税两列) */
.grid-table {
  display: grid;
  grid-template-columns:
    minmax(180px, 1fr)            /* 产品名称 flex 吃剩余 */
    minmax(100px, max-content)    /* 不含税 */
    minmax(100px, max-content)    /* 含税 */
    minmax(40px,  max-content)    /* 单位 */
    minmax(80px,  max-content)    /* 日期 */
    minmax(110px, max-content);   /* 分类 */
  grid-auto-rows: auto;
  width: 100%;
}

/* 每一行(表头/数据/骨架)继承父列模板 — subgrid 关键（行必须是 .grid-table 的直接子节点） */
.grid-table > .grid-header,
.grid-table > .grid-row {
  display: grid;
  grid-template-columns: subgrid;
  grid-column: 1 / -1;
  align-items: stretch;
}

/* 详情行不参与 subgrid（自身内部 grid 自适应），仅占满一行宽度 */
.grid-table > .grid-detail-row {
  grid-column: 1 / -1;
}

.grid-header {
  position: sticky;
  top: 0;
  z-index: 4;
  background: var(--surface-2, #f8fafc);
  box-shadow: 0 1px 0 var(--border);
}

.grid-cell {
  display: flex;
  align-items: center;
  padding: 8px 10px;
  border-right: 1px solid var(--border);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text, #0f172a);
  box-sizing: border-box;
  justify-content: flex-start;
}
.grid-cell:last-child { border-right: none; }

.grid-head-cell {
  font-weight: 700;
  font-size: 11.5px;
  color: var(--text-2);
  text-transform: none;
  letter-spacing: 0;
}
.grid-head-cell.sortable { cursor: pointer; user-select: none; transition: background 0.15s; }
.grid-head-cell.sortable:hover { background: var(--surface-3, #f1f5f9); }
.grid-head-cell.sorted { color: var(--primary); background: rgba(37,99,235,0.06); }
.grid-head-cell .sort-icon { margin-left: 4px; font-size: 10px; opacity: 0.6; }
.grid-head-cell.sorted .sort-icon { opacity: 1; }

.grid-cell.col-price   { justify-content: flex-end; padding-right: 14px; }
.grid-cell.col-tax_price { justify-content: flex-end; padding-right: 14px; }
.grid-cell.col-unit    { justify-content: center; }
.grid-cell.col-date    { justify-content: center; }
.grid-cell.col-category { justify-content: center; }
.grid-cell.col-breed   { white-space: normal; }

/* 行 */
.grid-row {
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.1s;
  background: var(--surface);
}
.grid-row:hover { background: rgba(37,99,235,0.04); }
.grid-row.stale-row { background: rgba(245,158,11,0.04); }
.grid-row.row-expanded { background: rgba(37,99,235,0.05); }
.grid-row:nth-child(even) { background: var(--surface-2, #f8fafc); }
.grid-row:nth-child(even):hover { background: rgba(37,99,235,0.06); }
.grid-row:nth-child(even).stale-row { background: rgba(245,158,11,0.06); }
.grid-row.stale-row:hover { background: rgba(245,158,11,0.1); }

/* 展开详情行(跨满所有列) */
.grid-detail-row {
  background: var(--surface-2, #f8fafc);
  border-bottom: 1px solid var(--border);
  padding: 0;
}

/* 骨架屏 — 复用同一 grid-table */
.skel .grid-cell { background: transparent; }
.skel .skel-head {
  font-size: 11.5px; font-weight: 700; color: var(--text-2);
  background: var(--surface-2);
}
.skel .skel-grid-row {
  background: linear-gradient(90deg, #f1f5f9 0%, #e2e8f0 50%, #f1f5f9 100%);
  background-size: 200% 100%;
  animation: skelShimmer 1.4s infinite linear;
}
.skel .skel-cell-bar {
  height: 22px;
  background: rgba(15,23,42,0.06);
  border-radius: 4px;
}
@keyframes skelShimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
.skeleton-footer { text-align: center; color: var(--text-3); font-size: 12px; padding: 16px; }

/* detail panel(沿用原样式) */
.detail-panel { padding: 14px 18px; }
.detail-panel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px 18px;
}
.detail-field { display: flex; flex-direction: column; gap: 2px; }
.detail-field.full-width { grid-column: 1 / -1; }
.detail-field-label { font-size: 11px; color: var(--text-3); font-weight: 600; }
.detail-field-value { font-size: 13px; color: var(--text); font-weight: 500; word-break: break-word; }
.detail-field-value.spec-full { white-space: pre-wrap; }
.detail-field-value.price-em { font-weight: 700; color: var(--primary); font-family: 'Courier New', monospace; }

/* 内容排版 */
.breed-cell { display: flex; flex-direction: column; gap: 2px; width: 100%; min-width: 0; }
.breed-name { font-weight: 600; font-size: 13px; color: var(--text); }
/* 跨页详情中心跳转链接样式 (2026-07-15 A) */
.ctx-breed-link {
  cursor: pointer;
  border-bottom: 1px dashed transparent;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
  padding: 1px 2px;
  border-radius: 3px;
}
.ctx-breed-link:hover {
  color: var(--primary);
  border-bottom-color: var(--primary);
  background: rgba(37, 99, 235, 0.05);
}
.breed-meta { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; font-size: 11px; color: var(--text-3); }
.meta-sep { color: var(--text-3); opacity: 0.6; }
.meta-tag.city-tag { color: var(--text-3); }
.price-main { font-family: 'Courier New', monospace; font-weight: 700; font-size: 13px; color: var(--text); }
.price-empty { font-size: 12px; color: var(--text-3); font-family: 'Courier New', monospace; }
.price-tax { font-size: 11px; color: var(--text-3); font-family: 'Courier New', monospace; }
.price-change { font-size: 11px; font-family: 'Courier New', monospace; font-weight: 600; }
.price-change.up { color: var(--status-alert, #ef4444); }
.price-change.down { color: var(--status-ok, #16a34a); }
.stale-date { color: var(--status-warn, #f59e0b); }
.cat-badge {
  display: inline-block; padding: 2px 8px; border-radius: 3px;
  font-size: 11px; background: rgba(37,99,235,0.1); color: var(--primary);
  font-weight: 600;
  max-width: 100%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.attr-cell { font-size: 11px; color: var(--text-3); }

/* 移动端 */
.table-mobile { display: none; }
@media (max-width: 768px) {
  .table-desktop { display: none; }
  .table-mobile { display: block; }
}
</style>
