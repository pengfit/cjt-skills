<!--
  列表页 — list tab 视图(2026-07-13 抽自 App.vue, 2026-07-15 Grid 化 + 内容感知列宽)
  - 模板来自原 App.vue `<template v-if="currentTab === 'list'">` 整块
  - state / computed / actions 全部委托给 useListSearch composable
  - 跨 tab 依赖(loadOverview)由 App.vue 通过 props 注入
  - 表格部分从原生 <table> 改为 CSS Grid + subgrid (2026-07-15)
  - 列宽按内容自适应：5 列都用 minmax(min, max-content)，但 max-content 在整列跨所有行求最大值
-->
<template>
  <!-- 2026-07-28:Phase 2 — 自研 drawer+CustomSelect 迁 Element Plus <el-drawer> + <el-form> + <el-select> -->
  <el-drawer
    v-model="showDrawer"
    direction="rtl"
    size="420px"
    title="更多筛选"
    :with-header="true"
  >
    <el-form label-position="top" class="list-filter-form">
      <el-form-item label="省份">
        <el-select
          v-model="searchProvince"
          placeholder="全部省份"
          filterable
          clearable
          style="width: 100%"
          @change="onProvinceChange"
        >
          <el-option v-for="p in provinceOptions" :key="p.key" :label="`${p.key} (${p.count})`" :value="p.key" />
        </el-select>
      </el-form-item>
      <el-form-item label="城市">
        <el-select
          v-model="searchCity"
          placeholder="全部城市"
          filterable
          clearable
          :disabled="!searchProvince"
          style="width: 100%"
          @change="onCityChange"
        >
          <el-option v-for="c in filteredCities" :key="c.key" :label="`${c.key} (${c.count})`" :value="c.key" />
        </el-select>
      </el-form-item>
      <el-form-item label="区县">
        <el-select
          v-model="searchCounty"
          placeholder="全部区县"
          filterable
          clearable
          :disabled="!searchProvince || !searchCity"
          style="width: 100%"
        >
          <el-option v-for="c in filteredCounties" :key="c.key" :label="`${c.key} (${c.count})`" :value="c.key" />
        </el-select>
      </el-form-item>
      <el-form-item label="日期范围">
        <div class="date-presets" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">
          <el-tag
            v-for="preset in datePresets"
            :key="preset.label"
            :type="dateRangeKey === preset.key ? 'primary' : 'info'"
            effect="plain"
            style="cursor: pointer"
            @click="applyDatePreset(preset)"
          >{{ preset.label }}</el-tag>
          <el-tag
            v-if="dateRangeKey === 'custom'"
            type="primary"
            effect="plain"
            style="cursor: pointer"
            @click="dateRangeKey = 'all'"
          >自定义 ✓</el-tag>
        </div>
        <el-date-picker
          v-model="dateRangeModel"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          style="width: 100%"
          @change="onDateRangeChange"
        />
      </el-form-item>
      <el-form-item label="价格区间">
        <div class="price-presets" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">
          <el-tag
            v-for="preset in pricePresets"
            :key="preset.label"
            :type="isPresetActive(preset) ? 'primary' : 'info'"
            effect="plain"
            style="cursor: pointer"
            @click="isPresetActive(preset) ? expandRange() : applyPreset(preset);"
          >{{ preset.label }}</el-tag>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <el-input-number v-model="priceMin" placeholder="最低价" :min="0" :step="0.01" :precision="2" style="flex:1" @keyup.enter="doSearch()" />
          <span style="color:#94a3b8">-</span>
          <el-input-number v-model="priceMax" placeholder="最高价" :min="0" :step="0.01" :precision="2" style="flex:1" @keyup.enter="doSearch()" />
        </div>
      </el-form-item>
      <el-form-item v-if="searchHistory.length && !searchKeyword" label="搜索历史">
        <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">
          <el-tag
            v-for="h in searchHistory.slice(0,8)"
            :key="h"
            type="info"
            effect="plain"
            style="cursor: pointer"
            @click="searchKeyword = h; doSearch()"
          >{{ h }}</el-tag>
          <el-button text type="primary" @click="clearHistory()">清空</el-button>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="resetSearch">重置</el-button>
      <el-button type="primary" @click="() => { showDrawer = false; doSearch(); }">🔍 确定</el-button>
    </template>
  </el-drawer>

    <div class="list-tree-layout">
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

        <!-- 2026-07-28:Phase 2 — 自研 CSS Grid 表格(含行展开)迁 Element Plus <el-table type="expand"> -->
        <div class="content-card table-desktop" v-else>
          <el-table
            :data="sortedData"
            :row-key="(item) => item.id"
            :expand-row-keys="expandedRow ? [expandedRow] : []"
            @row-click="toggleRow"
            @expand-change="onExpandChange"
            stripe
            class="list-el-table"
          >
            <el-table-column type="expand" width="40">
              <template #default="{ row }">
                <div class="detail-panel">
                  <div class="detail-panel-grid">
                    <div class="detail-field full-width">
                      <span class="detail-field-label">产品名称</span>
                      <span class="detail-field-value">{{ row.breed }}</span>
                    </div>
                    <div class="detail-field full-width" v-if="row.spec_clean || row.spec">
                      <span class="detail-field-label">规格型号</span>
                      <span class="detail-field-value spec-full">{{ row.spec_clean || row.spec || '-' }}</span>
                    </div>
                    <div class="detail-field full-width" v-if="row.attr && Object.keys(row.attr).length">
                      <span class="detail-field-label">规格属性</span>
                      <span class="detail-field-value"><AttrTags :attr="row.attr" /></span>
                    </div>
                    <div class="detail-field">
                      <span class="detail-field-label">价格</span>
                      <span class="detail-field-value price-em">{{ fmtCell(row.price) }} 元</span>
                    </div>
                    <div class="detail-field" v-if="row.tax_price && Number(row.tax_price) > 0">
                      <span class="detail-field-label">含税价</span>
                      <span class="detail-field-value">{{ fmtCell(row.tax_price) }} 元</span>
                    </div>
                    <div class="detail-field">
                      <span class="detail-field-label">单位</span>
                      <span class="detail-field-value">{{ row.unit || '-' }}</span>
                    </div>
                    <div class="detail-field">
                      <span class="detail-field-label">日期</span>
                      <span class="detail-field-value">{{ row.date || '-' }}</span>
                    </div>
                    <div class="detail-field">
                      <span class="detail-field-label">省份</span>
                      <span class="detail-field-value">{{ row.province || '-' }}</span>
                    </div>
                    <div class="detail-field">
                      <span class="detail-field-label">城市</span>
                      <span class="detail-field-value">{{ row.city || '-' }}</span>
                    </div>
                    <div class="detail-field" v-if="row.county">
                      <span class="detail-field-label">区县</span>
                      <span class="detail-field-value">{{ row.county }}</span>
                    </div>
                    <div class="detail-field" v-if="row.category">
                      <span class="detail-field-label">分类</span>
                      <span class="detail-field-value"><span class="cat-badge">{{ row.category }}</span></span>
                    </div>
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="品种" min-width="280" sortable="custom">
              <template #default="{ row }">
                <div class="breed-cell">
                  <span
                    class="breed-name ctx-breed-link"
                    :title="`${row.breed_clean || row.breed} (点击查看详情)`"
                    @click.stop="openBreedDetail(row)"
                    v-html="highlightKeyword(row.breed)"
                  ></span>
                  <div class="breed-meta">
                    <AttrTags :attr="row.attr" />
                    <span class="meta-sep" v-if="row.city">·</span>
                    <span class="meta-tag city-tag" v-if="row.city">{{ row.city }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="规格" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ row.spec_clean || row.spec || '-' }}</template>
            </el-table-column>

            <el-table-column label="价格" width="120" align="right" sortable="custom">
              <template #default="{ row }">
                <div class="price-main">{{ fmtCell(row.price) }}</div>
                <div class="price-change" v-if="getPriceChange(row)" :class="getPriceChange(row).cls" style="pointer-events:none">{{ getPriceChange(row).text }}</div>
              </template>
            </el-table-column>

            <el-table-column label="含税价" width="110" align="right">
              <template #default="{ row }">
                <div class="price-main" v-if="row.tax_price && Number(row.tax_price) > 0">{{ fmtCell(row.tax_price) }}</div>
                <div class="price-empty" v-else>—</div>
              </template>
            </el-table-column>

            <el-table-column label="单位" prop="unit" width="80" align="center" />

            <el-table-column label="属性" min-width="200">
              <template #default="{ row }">
                <div class="attr-cell"><AttrTags :attr="row.attr" /></div>
              </template>
            </el-table-column>

            <el-table-column label="日期" width="120" sortable="custom" align="center">
              <template #default="{ row }">
                <span :class="{ 'stale-date': isStale(row.date) }">{{ staleText(row.date) || row.date || '-' }}</span>
              </template>
            </el-table-column>

            <el-table-column label="分类" width="140">
              <template #default="{ row }">
                <span class="cat-badge" :title="row.category || ''">{{ row.category || '-' }}</span>
              </template>
            </el-table-column>

            <el-table-column label="省份" prop="province" width="100" show-overflow-tooltip />
            <el-table-column label="城市" prop="city" width="100" show-overflow-tooltip />
          </el-table>
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

// const CategoryTreeSidebar = defineAsyncComponent(() => import('./CategoryTreeSidebar.vue')) // 2026-07-28 删除 list-tree-panel

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

// 2026-07-28:Phase 2 — <el-table type="expand"> 行点击 + 展开状态同步
function onRowClick(row) {
  expandedRow.value = expandedRow.value === row.id ? null : row.id
}
function onExpandChange(row, expandedRows) {
  // 同步 el-table 内部 expand-row-keys 到外部 expandedRow
  expandedRow.value = expandedRows.length ? row.id : null
}

// 2026-07-28:Phase 2 — <el-date-picker daterange> v-model 适配(dateFrom + dateTo → 数组)
const dateRangeModel = computed({
  get: () => (dateFrom.value && dateTo.value) ? [dateFrom.value, dateTo.value] : [],
  set: (val) => {
    if (val && val[0] && val[1]) {
      dateFrom.value = val[0]
      dateTo.value = val[1]
      dateRangeKey.value = 'custom'
    } else {
      dateFrom.value = ''
      dateTo.value = ''
      dateRangeKey.value = 'all'
    }
  }
})

const props = defineProps({
  bundle: { type: Object, required: true },
  // categoryPanelCollapsed: { type: Boolean, default: false }, // 2026-07-28 删除 list-tree-panel
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
  onCityChange, onProvinceChange, resetSearch,  // 2026-07-28 去掉 onCategoryTreeSelect
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
/* 2026-07-28 Phase 2 cleanup:
   桌面端表格已迁 <el-table>,以下自研 CSS Grid 样式仅骨架屏继续用 .grid-table/.grid-row/.grid-cell。
   已删除: .page-header / .grid-scroll / .grid-head-cell* / .grid-cell.col-* /
            .grid-row.stale-row / .grid-row.row-expanded / .grid-detail-row /
            .grid-table > .grid-detail-row / .price-tax / @media 内 .quick-filters 等死代码。 */
.table-desktop { padding: 0; }

/* 骨架屏 grid container — 7 列定义(2026-07-19: 价格拆为不含税/含税两列,Phase 2 后实际数据表用 el-table,这里仅给 skeleton 用) */
.grid-table {
  display: grid;
  grid-template-columns:
    minmax(180px, 1fr)
    minmax(100px, max-content)
    minmax(100px, max-content)
    minmax(40px,  max-content)
    minmax(80px,  max-content)
    minmax(110px, max-content);
  grid-auto-rows: auto;
  width: 100%;
}

/* 骨架行继承父列模板 — subgrid */
.grid-table > .grid-header,
.grid-table > .grid-row {
  display: grid;
  grid-template-columns: subgrid;
  grid-column: 1 / -1;
  align-items: stretch;
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

/* 骨架行(在 skeleton-card 内,真实数据表用 el-table 接管) */
.grid-row {
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.1s;
  background: var(--surface);
}
.grid-row:hover { background: rgba(37,99,235,0.04); }
.grid-row:nth-child(even) { background: var(--surface-2, #f8fafc); }
.grid-row:nth-child(even):hover { background: rgba(37,99,235,0.06); }

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

/* detail panel(el-table expand 行用) */
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

/* el-table 列内容排版 */
.breed-cell { display: flex; flex-direction: column; gap: 2px; width: 100%; min-width: 0; }
.breed-name { font-weight: 600; font-size: 13px; color: var(--text); }
/* 跨页详情中心跳转链接样式 */
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

/* 移动端适配 — 桌面端走 el-table,移动端走 .table-mobile 卡片栈 */
@media (max-width: 768px) {
  .table-desktop { display: none; }
  .table-mobile  { display: block; }
  /* skeleton grid-table 适配移动端块级布局 */
  .grid-table { display: block !important; }
  .grid-table tbody, .grid-table .grid-row, .grid-table tr { display: block !important; width: 100% !important; }
  .grid-table td, .grid-table .grid-cell { display: flex !important; justify-content: space-between !important; padding: 4px 0 !important; border: none !important; word-break: break-word; }
  .filter-bar { flex-direction: column !important; align-items: stretch !important; gap: 8px !important; padding: 10px !important; }
  .filter-bar-input, .filter-bar-select { width: 100% !important; min-height: 44px !important; font-size: 15px !important; }
}
</style>
