<!--
  列表页 — list tab 视图(2026-07-13 抽自 App.vue)
  - 模板来自原 App.vue `<template v-if="currentTab === 'list'">` 整块
  - state / computed / actions 全部委托给 useListSearch composable
  - 跨 tab 依赖(loadOverview)由 App.vue 通过 props 注入
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
            :options="(props.overview?.by_province || []).map(p => ({ key: p.province, count: p.count }))"
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
        <!-- Price range presets exposed in drawer -->
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
              @click="isPresetActive(preset) ? expandRange() : applyPreset(preset); /* 选中不搜索,等确定 */"
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
  <!-- Drawer backdrop for mobile/desktop click-outside close -->
  <Transition name="fade">
    <div class="drawer-backdrop" v-if="showDrawer" @click="showDrawer = false"></div>
  </Transition>

    <!-- 列表页:左侧分类树 + 右侧产品表格 -->
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

      <!-- Content Area -->
      <main class="content-area">

      <!-- 分类面包屑 -->
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
        <!-- 日期预设平铺(A.2026-07-12 P0):默认 7 天 + 随时切换 -->
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
        <!-- 导出(P3-batch3):利用已有 useExport,支持 CSV / JSON -->
        <button
          class="btn-export"
          :disabled="!sortedData.length"
          :title="sortedData.length ? `导出 ${sortedData.length} 条记录为 CSV(当前筛选)` : '请先加载数据'"
          @click="exportSearchResultCsv"
        >📊 导出 CSV</button>

        <!-- Active Filter Tags (inside filter-bar) -->
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

        <!-- Toolbar (standalone, outside Transition) -->
        <!-- ========== TABLE or CHART or LOADING or EMPTY ========== -->

        <!-- Skeleton loading - uses flex:0 0 Npx so widths always match table -->
        <!-- 加载时仍保留表头文字,避免"表格消失"错觉(fix 2026-07-12 P3-batch2) -->
        <div class="content-card skeleton-card" v-if="loading">
          <div class="skeleton-header">
            <div class="skeleton-col has-label" v-for="col in visibleColumns" :key="col.key" :style="{ flex: `0 0 ${col.width}px`, minWidth: col.width + 'px' }">{{ col.label }}</div>
          </div>
          <div class="skeleton-row" v-for="i in 8" :key="i">
            <div class="skeleton-col" v-for="col in visibleColumns" :key="col.key" :style="{ flex: `0 0 ${col.width}px`, minWidth: col.width + 'px' }"></div>
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

          <!-- Data Table(桌面端) -->
        <div class="content-card table-desktop" v-else>
          <div class="table-scroll">
            <table class="data-table compact-table">
              <thead>
                <tr>
                  <th
                    v-for="col in visibleColumns"
                    :key="col.key"
                    :class="['col-' + col.key, { sorted: sortKey === col.key, sortable: col.sortable }]"
                    :style="{ width: col.width + 'px', minWidth: col.width + 'px' }"
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
                <template v-for="(item, idx) in sortedData" :key="item.id || idx">
                <tr
                  class="data-row"
                  :class="{ 'stale-row': isStale(item.date), 'row-expanded': expandedRow === (item.id || idx) }"
                  @click="toggleRow(item, idx)"
                >
                  <td
                    v-for="col in visibleColumns"
                    :key="col.key"
                    :class="['col-' + col.key, getCellClass(col.key, item)]"
                    :style="{ width: col.width + 'px', minWidth: col.width + 'px' }"
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
                      <div class="price-tax" v-if="item.tax_price && Number(item.tax_price) > 0">含税 {{ fmtCell(item.tax_price) }}</div>
                      <div class="price-change" v-if="getPriceChange(item)" :class="getPriceChange(item).cls" style="pointer-events:none">{{ getPriceChange(item).text }}</div>
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
                      <span class="cat-badge">{{ item.category || '-' }}</span>
                    </template>
                    <template v-else>{{ item[col.key] ?? '-' }}</template>
                  </td>
                </tr>
                <!-- 展开详情行 -->
                <tr v-if="expandedRow === (item.id || idx)" class="detail-row">
                  <td :colspan="visibleColumns.length">
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
                  </td>
                </tr>
                </template>
              </tbody>
            </table>
          </div>

          <!-- 移动端卡片视图 -->
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
                  <div class="mobile-card-unit">{{ item.unit || '' }}</div>
                  <div class="mobile-card-date" :class="{ 'stale-date': isStale(item.date) }">{{ staleText(item.date) || item.date || '-' }}</div>
                </div>
              </div>
              <!-- 展开详情 -->
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

        <!-- 列配置弹层(右上角 ⓘ 触发) -->
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
      </div> <!-- /.list-tree-layout -->
</template>

<script setup>
import { defineAsyncComponent } from 'vue'
import AttrTags from './AttrTags.vue'
import CustomSelect from './CustomSelect.vue'

const CategoryTreeSidebar = defineAsyncComponent(() => import('./CategoryTreeSidebar.vue'))

const props = defineProps({
  /** useListSearch composable 返回的 bundle(refs + computed + actions)。
   * 由 App.vue 在顶层调用 useListSearch 持有,保证切 tab 不丢 state。 */
  bundle: { type: Object, required: true },
  /** 全局 overview(模板里用 by_province 给省份下拉做选项) */
  overview: { type: Object, required: true },
  /** 分类面板收起状态(由 App.vue 持有,跨页面持久) */
  categoryPanelCollapsed: { type: Boolean, default: false },
})

// 从 bundle 拆出 refs / computed / actions，setup 顶层变量会被模板自动 expose。
const {
  // refs (template 直接 v-model)
  searchKeyword, searchProvince, searchCity, searchCounty,
  searchCategoryCode, searchCategoryLevel,
  priceMin, priceMax, dateFrom, dateTo, dateRangeKey, datePresets,
  pricePresets, categoryBreadcrumb,
  searchResult, searchPage, jumpPage, pageSize, pageSizeOptions,
  loading, searchError,
  cityOptions, countyOptions,
  sortKey, sortDir, expandedRow,
  searchHistory, allColumns, showColConfig, showDrawer, colConfigRef,
  toast,
  // computed
  visibleColumns, filteredCities, filteredCounties, sortedData,
  pageStart, pageEnd, pageRange,
  // actions
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

defineExpose({ loadCategoryOptions })
</script>