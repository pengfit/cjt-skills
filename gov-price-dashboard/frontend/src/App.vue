<template>
  <div class="dashboard with-sidebar" :class="{ 'mobile-sidebar-open': mobileSidebarOpen }">

    <!-- ========== SKIP LINK (a11y 2026-07-12 P2-3) ========== -->
    <a href="#main-content" class="skip-link">跳到主内容</a>

    <!-- ========== TOP BAR(统一 TopBar.vue) ========== -->
    <TopBar
      :overview="overview"
      :alerts="alerts"
      :last-refresh="lastRefresh"
      :last-refresh-ago="lastRefreshAgo"
      @toggle-sidebar="mobileSidebarOpen = !mobileSidebarOpen"
      @open-cmd-palette="showCmdPalette = true"
      @go-health="goHealth"
      @go-list="goList"
    />

    <!-- ========== DASHBOARD BODY (sidebar + main) ========== -->
    <div class="dashboard-body">

    <!-- ========== SIDEBAR(统一 Sidebar.vue) ========== -->
    <Sidebar
      :groups="sidebarGroups"
      :current-tab="currentTab"
      :open="mobileSidebarOpen"
      @close="mobileSidebarOpen = false"
      @navigate="mobileSidebarOpen = false"
    />

    <!-- ========== MAIN CONTENT ========== -->
    <main id="main-content" class="main-content" tabindex="-1">

    <!-- Filter Bar (full-width, above main content) -->
    <template v-if="currentTab === 'list'">
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
              :options="(overview.by_province || []).map(p => ({ key: p.province, count: p.count }))"
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
          <!-- 日期范围:时序看板刚需(fix 2026-07-12) -->
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
      <div class="list-tree-layout" v-if="currentTab === 'list'">
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
        <!-- 日期预设平铺(A.2026-07-12 P0)：默认 7 天 + 随时切换 -->
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
      </main>
      </div> <!-- /.list-tree-layout -->
    </template>

    <!-- Distribution page -->
    <template v-if="currentTab === 'dist'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel">
        <DistributionChart
          :keyword="searchKeyword"
          :province="searchProvince"
          :city="searchCity"
        />
      </div>
    </template>

    <template v-if="currentTab === 'trend'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel"><PriceTrendView /></div>
    </template>

    <template v-if="currentTab === 'cockpit'">
      <div class="scroll-panel">
        <CockpitView />
      </div>
    </template>

    <template v-if="currentTab === 'category'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel"><CategoryView /></div>
    </template>

    <template v-if="currentTab === 'sync'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel"><SyncView /></div>
    </template>

    <template v-if="currentTab === 'health'">
      <div class="scroll-panel"><DataHealthView /></div>
    </template>

    <template v-if="currentTab === 'rules'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel"><VecRulesView /></div>
    </template>

    <template v-if="currentTab === 'taxonomy'">
      <div v-if="tabLoading" class="tab-loading"><div class="loading-spinner"></div><span>加载中...</span></div>
      <div v-else class="scroll-panel"><CategoryTaxonomyView /></div>
    </template>

    </main>
    </div>
  </div>

  <!-- Toast -->
  <Transition name="toast">
    <div v-if="toast.show" class="toast" :class="'toast--' + (toast.type || 'info')">{{ toast.msg }}</div>
  </Transition>

  <!-- 命令面板 ⌘K -->
  <CmdPalette
    :show="showCmdPalette"
    :items="cmdItems"
    placeholder="搜索页面、命令... (⌘K)"
    @close="showCmdPalette = false"
    @select="onCmdSelect"
  />
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { defineAsyncComponent } from 'vue'
import axios from 'axios'
import AttrTags from './components/AttrTags.vue'
import CustomSelect from './components/CustomSelect.vue'
import { exportCsvAsFile, withTimestamp } from './composables/useExport.js'
// D.2026-07-12 统一数字格式化
import { useFormatNumber } from './composables/useFormatNumber.js'
// 路由级 view 全部 async(首屏不加载,切 tab 时才按需下载;2026-07-09 优化)
const DistributionChart = defineAsyncComponent(() => import('./components/DistributionChart.vue'))
const PriceTrendView = defineAsyncComponent(() => import('./components/PriceTrendView.vue'))
const CategoryView = defineAsyncComponent(() => import('./components/CategoryView.vue'))
const SyncView = defineAsyncComponent(() => import('./components/SyncView.vue'))
const DataHealthView = defineAsyncComponent(() => import('./components/DataHealthView.vue'))
const CockpitView = defineAsyncComponent(() => import('./components/CockpitView.vue'))
const VecRulesView = defineAsyncComponent(() => import('./components/VecRulesView.vue'))
const CategoryTaxonomyView = defineAsyncComponent(() => import('./components/CategoryTaxonomyView.vue'))
const CategoryTreeSidebar = defineAsyncComponent(() => import('./components/CategoryTreeSidebar.vue'))
// 全局小工具(CmdPalette 始终挂载,保留 sync import;AttrTags/CustomSelect 多 tab 复用 → sync)
import CmdPalette from './components/CmdPalette.vue'
import Sidebar from './components/layout/Sidebar.vue'
import TopBar from './components/layout/TopBar.vue'
import { TAB_ROUTES, legacyTabPath } from './router'

const route = useRoute()
const router = useRouter()
// D.2026-07-12 统一数字格式化
const fmt = useFormatNumber()
// 当前 tab key:来自路由 name,模板中自动解包
const currentTab = computed(() => route.name || 'cockpit')

const API = import.meta.env.VITE_API_URL || '/api'

// ============================================================
// STATE
// ============================================================
// 侧栏分组:复用 router/index.js 的 TAB_ROUTES,数字键 1-9 用 index 直接定位
// 新增 tab 只需改 router/index.js 一处
const TAB_ICONS = {
  cockpit: '🛸', list: '📋', category: '📁', dist: '📊',
  trend: '📈', sync: '🔄', health: '❤️', rules: '⚙️', taxonomy: '🏷️',
}
function sidebarItems(keys) {
  return TAB_ROUTES
    .map((r, idx) => ({ r, idx }))
    .filter(({ r }) => keys.includes(r.key))
    .map(({ r, idx }) => ({
      key: r.key,
      label: r.label,
      path: r.path,
      icon: TAB_ICONS[r.key] || '·',
      shortcut: String(idx + 1),  // 数字键 1-9 badge,跟全局键盘监听对齐
    }))
}
const sidebarGroups = computed(() => ([
  // 4 模块拆开(2026-07-10):数据浏览 + 数据采集 + 数据治理 + 价格可视化
  { key: 'view',    label: '数据浏览',    items: sidebarItems(['cockpit', 'list', 'category']) },
  { key: 'collect', label: '数据采集',    items: sidebarItems(['sync', 'health']) },
  { key: 'govern',  label: '数据治理',    items: sidebarItems(['rules', 'taxonomy']) },
  { key: 'viz',     label: '价格可视化',  items: sidebarItems(['dist', 'trend']) },
]))

const mobileSidebarOpen = ref(false)
const showCmdPalette = ref(false)  // ⌘K 命令面板
const categoryPanelCollapsed = ref(false)  // 分类面板收起
watch(() => route.name, () => { mobileSidebarOpen.value = false })  // 切 tab 后自动关闭移动侧边栏

// ⌘K 命令面板项(fix 2026-07-12 P3-batch2:加 group 分组)
const cmdItems = computed(() => {
  const navItems = TAB_ROUTES.map((t, i) => ({
    id: 'tab:' + t.key,
    group: '页面跳转',
    label: t.label,
    icon: ['🛩️', '📋', '📊', '📈', '🗺️', '🔄', '💚', '🧩', '🗂️'][i] || '·',
    hint: '跳转到 ' + t.label,
    shortcut: String(i + 1),
    action: () => router.push(t.path),
  }))
  const actionItems = [
    {
      id: 'search:open',
      group: '动作',
      label: '聚焦产品搜索',
      icon: '🔍',
      hint: '跳到"全部数据"页并聚焦搜索框',
      shortcut: '/',
      action: () => {
        router.push(legacyTabPath('list'))
        nextTick(() => document.querySelector('.filter-bar-input')?.focus())
      },
    },
    {
      id: 'drawer:open',
      group: '动作',
      label: '打开更多筛选',
      icon: '⚙️',
      hint: '弹出筛选抽屉(仅在"全部数据"生效)',
      action: () => { if (currentTab.value === 'list') showDrawer.value = true },
    },
  ]
  // 数据查询:点击高分页可点击进 list 页
  const queryItems = overview.value && overview.value.by_province
    ? overview.value.by_province.slice(0, 5).map(p => ({
        id: 'prov:' + p.province,
        group: '数据查询',
        label: '查看 ' + p.province + ' 价格',
        icon: '🔎',
        hint: `${p.province} · ${fmt.count(p.count, '条记录')}`,
        action: () => router.push({ path: legacyTabPath('list'), query: { province: p.province } }),
      }))
    : []
  return [...navItems, ...actionItems, ...queryItems]
})

function onCmdSelect(item) {
  // 由组件内部调用 action,这里只处理额外逻辑
}
const overview = ref({ total_docs: 0, total_provinces: 0, total_cities: 0, avg_price: 0, max_price: 0, min_price: 0, by_province: [] })

// 数据新鲜度告警(2026-07-12 P1-4):来自 /api/skill-updates,15 分钟轮询
const alerts = ref({ count: 0, veryStaleCount: 0, updates: [] })
const lastRefresh = ref('')   // 接口响应的 ISO 时间,用于 tooltip
const lastRefreshAgo = ref('') // "3 分钟前" 等动态文案
let alertsTimer = null
let clockTimer = null
const ALERTS_POLL_MS = 15 * 60 * 1000  // 与驾驶舱轮询节拍对齐

async function loadAlerts() {
  try {
    const d = await loadAPI(`${API}/skill-updates`)
    if (!d || !Array.isArray(d.updates)) return
    const updates = d.updates
    const nonFresh = updates.filter(u => u.status !== 'fresh')
    alerts.value = {
      count: nonFresh.length,
      veryStaleCount: nonFresh.filter(u => u.status === 'very_stale').length,
      updates,
    }
    if (d.now) lastRefresh.value = d.now
    refreshAgoText()  // 拿到 d.now 后立即刷一次,避免等 60s 定时器(2026-07-12 P1-4 fix)
  } catch (e) {
    // 静默失败:告警非关键路径,不要因网络抖动让顶栏报错
  }
}

function formatTimeAgo(iso) {
  if (!iso) return ''
  const dt = new Date(iso)
  if (isNaN(dt.getTime())) return ''
  const diffSec = Math.floor((Date.now() - dt.getTime()) / 1000)
  if (diffSec < 0) return '刚刚'
  if (diffSec < 60) return `${diffSec} 秒前`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  const diffDay = Math.floor(diffHour / 24)
  return `${diffDay} 天前`
}

function refreshAgoText() {
  lastRefreshAgo.value = lastRefresh.value ? `更新于 ${formatTimeAgo(lastRefresh.value)}` : ''
}

function goHealth() {
  router.push(legacyTabPath('health'))
}

// 顶栏 KPI 钻取（fix 2026-07-12 P3-batch1）：省份/城市可点击进 list 页
function goList(payload) {
  const scope = payload?.scope || 'all'
  // 当前 list 页用抽屉筛选驱动，scope 目前只置位，后续可扩展为预填筛选
  router.push({ path: legacyTabPath('list'), query: { _from: scope } })
}

// 导出搜索结果为 CSV（fix 2026-07-12 P3-batch3）：按 visibleColumns 顺序输出当前渲染行
function exportSearchResultCsv() {
  if (!sortedData.value.length) return
  const cols = visibleColumns.value
  const header = cols.map(c => c.label)
  const rows = [header]
  for (const item of sortedData.value) {
    const row = cols.map(c => {
      const v = item[c.key]
      if (v == null) return ''
      if (typeof v === 'object') return JSON.stringify(v)
      return String(v)
    })
    rows.push(row)
  }
  const fname = `搜索结果-${searchKeyword.value || '全部'}-${withTimestamp()}.csv`
  exportCsvAsFile(rows, fname)
}
const searchKeyword = ref('')
const searchProvince = ref('')
const searchCity = ref('')
const searchCounty = ref('')
const searchCategoryCode = ref('')   // 分类树选中节点的代码(L1/L2/L3)
const searchCategoryLevel = ref('')    // 节点层级: 'l1' | 'l2' | 'l3'
const categoryOptions = ref([])
const priceMin = ref('')
const priceMax = ref('')
const searchPage = ref(1)
const loading = ref(true)  // 初始即加载态,避免首次渲染闪空态
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

// Row expand
const expandedRow = ref(null)
function toggleRow(item, idx) {
  const key = item.id || idx
  expandedRow.value = expandedRow.value === key ? null : key
}

// Category breadcrumb
const categoryBreadcrumb = ref([])  // [{ code, name }]

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

// Date presets(fix 2026-07-12:时序看板刚需)
const dateFrom = ref('')
const dateTo = ref('')
const dateRangeKey = ref('all')
const datePresets = [
  { key: 'all',    label: '全部' },
  { key: '7d',     label: '近 7 天' },
  { key: '30d',    label: '近 30 天' },
  { key: '90d',    label: '近 90 天' },
  { key: 'ytd',    label: '今年' },
]

function applyDatePreset(preset) {
  dateRangeKey.value = preset.key
  const today = new Date()
  const fmt = d => d.toISOString().slice(0, 10)
  dateTo.value = fmt(today)
  if (preset.key === 'all') {
    dateFrom.value = ''
    dateTo.value = ''
  } else if (preset.key === '7d') {
    dateFrom.value = fmt(new Date(today.getTime() - 7 * 86400000))
  } else if (preset.key === '30d') {
    dateFrom.value = fmt(new Date(today.getTime() - 30 * 86400000))
  } else if (preset.key === '90d') {
    dateFrom.value = fmt(new Date(today.getTime() - 90 * 86400000))
  } else if (preset.key === 'ytd') {
    dateFrom.value = `${today.getFullYear()}-01-01`
  }
}

// Toast
const toast = ref({ show: false, msg: '', type: 'info' })
const searchError = ref(false)
const tabLoading = ref(false)

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
  return s > 0 ? fmt.int(s) : '0'
})

const pageEnd = computed(() => {
  const e = Math.min(Number(searchPage.value) * pageSize.value, searchResult.value.total || 0)
  return fmt.int(e)
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

function onCityChange() {
  searchCounty.value = ''
  // 不自动搜索,等用户点击「确定」
}

function onProvinceChange() {
  searchCity.value = ''
  searchCounty.value = ''
}

function onCategoryTreeSelect(node) {
  // 根据节点包含的字段判断层级
  if (node.l3) {
    searchCategoryCode.value = node.l3
    searchCategoryLevel.value = 'l3'
    // 构建面包屑:parentPath + 当前节点
    const parents = (node.parentPath || []).map(p => ({ code: p.code, name: p.name || p.code }))
    categoryBreadcrumb.value = [...parents, { code: node.l3, name: node.name_l3 || node.l3 }]
  } else if (node.l2) {
    searchCategoryCode.value = node.l2
    searchCategoryLevel.value = 'l2'
    const parents = (node.parentPath || []).map(p => ({ code: p.code, name: p.name || p.code }))
    categoryBreadcrumb.value = [...parents, { code: node.l2, name: node.name_l2 || node.l2 }]
  } else if (node.l1) {
    searchCategoryCode.value = node.l1
    searchCategoryLevel.value = 'l1'
    categoryBreadcrumb.value = [{ code: node.l1, name: node.name_l1 || node.l1 }]
  }
  doSearch()
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
  const maxPage = searchResult.value.pages || 1
  if (p < 1 || p > maxPage) {
    showToast(`页码超出范围,当前仅第 1-${maxPage} 页`)
    return
  }
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
    // 分类树筛选(按层级传递不同参数)
    if (searchCategoryCode.value && searchCategoryLevel.value) {
      const levelKey = 'category_' + searchCategoryLevel.value
      params[levelKey] = searchCategoryCode.value
    }
    if (priceMin.value) params.price_min = priceMin.value
    if (priceMax.value) params.price_max = priceMax.value
    // 日期范围(fix 2026-07-12)
    if (dateFrom.value) params.date_from = dateFrom.value
    if (dateTo.value) params.date_to = dateTo.value
    params.page = Number(pageOverride || searchPage.value)
    params.page_size = Number(pageSize.value)
    if (isNaN(params.page) || params.page < 1) params.page = 1

    const { data: res } = await axios.get(`${API}/search`, { params })
    searchResult.value = res || {}

    // 同步筛选状态到 URL(fix 2026-07-12)
    syncToQuery()

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
    showToast('请求失败:' + (e.message || '网络错误'))
  } finally {
    loading.value = false
  }
}

function resetSearch() {
  searchKeyword.value = ''
  searchProvince.value = ''
  searchCity.value = ''
  searchCounty.value = ''
  searchCategoryCode.value = ''
  searchCategoryLevel.value = ''
  categoryBreadcrumb.value = []
  priceMin.value = ''
  priceMax.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  dateRangeKey.value = 'all'
  searchPage.value = '1'
  jumpPage.value = 1
  sortKey.value = ''
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
  return fmt.price(n).replace('¥', '')  // 表格里不需要货币符,只显示数字部分
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
  // 不自动搜索,等用户点击「确定」
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
  showToast(`已导出 ${sortedData.value.length} 条数据`)
}

async function refreshAll() {
  await Promise.all([loadOverview(), loadCityOptions()])
  if (searchKeyword.value || searchProvince.value || searchCity.value || searchCounty.value || priceMin.value || priceMax.value) {
    await doSearch()
  }
  showToast('数据已刷新')
}

function showToast(msg, type = 'info') {
  toast.value = { show: true, msg, type }
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

// Tab switch loading feedback
watch(() => route.name, (newTab, oldTab) => {
  if (newTab !== 'list') {
    tabLoading.value = true
    setTimeout(() => { tabLoading.value = false }, 100)
  }
})

// ============================================================
// API
// ============================================================
async function loadAPI(url) {
  try { return (await axios.get(url)).data } catch { return {} }
}

// 内存缓存(避免重复请求)
let _overviewCache = null
let _overviewCacheAt = 0
let _filterOptionsCache = null
let _filterOptionsCacheAt = 0
const CACHE_TTL = 30 * 1000  // 30s

async function loadOverview() {
  if (_overviewCache && Date.now() - _overviewCacheAt < CACHE_TTL) {
    overview.value = _overviewCache
    return _overviewCache
  }
  // HUD 只需要 4 个数字 + 省份选项(fix 2026-07-12:categoryOptions 已独立)
  const d = await loadAPI(`${API}/stats/overview`)
  _overviewCache = d || { total_docs: 0, total_provinces: 0, total_cities: 0, avg_price: 0, by_province: [] }
  _overviewCacheAt = Date.now()
  overview.value = _overviewCache
  return _overviewCache
}

// 分类选项独立加载(fix 2026-07-12:避免被 overview 30s 缓存影响刷新频次)
let _categoryCache = null
let _categoryCacheAt = 0
async function loadCategoryOptions() {
  const CATEGORY_TTL = 60 * 1000  // 60s
  if (_categoryCache && Date.now() - _categoryCacheAt < CATEGORY_TTL) {
    categoryOptions.value = _categoryCache
    return
  }
  const d = await loadAPI(`${API}/stats/categories?size=500`)
  const list = (d?.data || []).map(c => ({ key: c.key, count: c.count, label: c.key }))
    .sort((a, b) => a.key.localeCompare(b.key, 'zh-CN'))
  _categoryCache = list
  _categoryCacheAt = Date.now()
  categoryOptions.value = list
}

async function loadCityOptions() {
  if (_filterOptionsCache && Date.now() - _filterOptionsCacheAt < CACHE_TTL) {
    cityOptions.value = _filterOptionsCache.cities || []
    countyOptions.value = _filterOptionsCache.counties || []
    provinceCityMap.value = _filterOptionsCache.provinceCityMap || {}
    return _filterOptionsCache
  }
  const d = await loadAPI(`${API}/filter-options`)
  _filterOptionsCache = d || {}
  _filterOptionsCacheAt = Date.now()
  if (_filterOptionsCache) {
    cityOptions.value = _filterOptionsCache.cities || []
    countyOptions.value = _filterOptionsCache.counties || []
    provinceCityMap.value = _filterOptionsCache.provinceCityMap || {}
  }
  return _filterOptionsCache
}

async function onMount() {
  // 需 4 个端点:overview、filter-options、categories、search
  // 先从 URL 恢复筛选状态(fix 2026-07-12:顺序重要)
  restoreFromQuery()
  await Promise.all([loadOverview(), loadCityOptions(), loadCategoryOptions(), doSearch()])
}

// 从 URL query 恢复筛选状态(fix 2026-07-12)
// 注意:onMounted 触发时 vue-router 还没把 location.search 同步到 route.query
// 直接从 window.location.search 读,避免被"空 query"覆盖
function readQueryFromLocation() {
  const sp = new URLSearchParams(window.location.search)
  const out = {}
  for (const [k, v] of sp.entries()) out[k] = v
  return out
}

function restoreFromQuery() {
  const q = readQueryFromLocation()
  if (q.keyword) searchKeyword.value = String(q.keyword)
  if (q.province) searchProvince.value = String(q.province)
  if (q.city) searchCity.value = String(q.city)
  if (q.county) searchCounty.value = String(q.county)
  if (q.category_code) {
    searchCategoryCode.value = String(q.category_code)
    searchCategoryLevel.value = String(q.category_level || 'l3')
  }
  // 日期范围：URL 有则用 URL,无则默认 7 天(A.2026-07-12 P0:首屏不再空白)
  if (q.date_from || q.date_to) {
    if (q.date_from) dateFrom.value = String(q.date_from)
    if (q.date_to) dateTo.value = String(q.date_to)
    dateRangeKey.value = 'custom'
  } else if (dateRangeKey.value === 'all' && !dateFrom.value && !dateTo.value) {
    applyDatePreset({ key: '7d', label: '近 7 天' })
  }
  if (q.price_min) priceMin.value = String(q.price_min)
  if (q.price_max) priceMax.value = String(q.price_max)
}

// 将当前筛选状态同步到 URL query(不刷页)
function syncToQuery() {
  if (currentTab.value !== 'list') return
  const q = {}
  if (searchKeyword.value.trim()) q.keyword = searchKeyword.value.trim()
  if (searchProvince.value) q.province = searchProvince.value
  if (searchCity.value) q.city = searchCity.value
  if (searchCounty.value) q.county = searchCounty.value
  if (searchCategoryCode.value) {
    q.category_code = searchCategoryCode.value
    q.category_level = searchCategoryLevel.value
  }
  if (priceMin.value) q.price_min = priceMin.value
  if (priceMax.value) q.price_max = priceMax.value
  if (dateFrom.value) q.date_from = dateFrom.value
  if (dateTo.value) q.date_to = dateTo.value
  router.replace({ query: q }).catch(() => {})
}

onMounted(() => {
  restoreFromQuery()
  document.addEventListener('click', handleDocClick)
})

onMounted(onMount)

// 数据新鲜度轮询 + 时钟(2026-07-12 P1-4)
onMounted(() => {
  loadAlerts()
  alertsTimer = setInterval(loadAlerts, ALERTS_POLL_MS)
  clockTimer = setInterval(refreshAgoText, 60 * 1000)
})
onBeforeUnmount(() => {
  if (alertsTimer) clearInterval(alertsTimer)
  if (clockTimer) clearInterval(clockTimer)
})

// Keyboard shortcuts
onMounted(() => {
  document.addEventListener('keydown', e => {
    // Esc 关闭所有层
    if (e.key === 'Escape') {
      showColConfig.value = false
      if (showDrawer.value) showDrawer.value = false
      showCmdPalette.value = false
    }
    // ⌘K / Ctrl+K / / 打开命令面板
    const isInputFocused = e.target.matches && e.target.matches('input, textarea, select, [contenteditable]')
    if ((e.ctrlKey && e.key === 'k') || (e.metaKey && e.key === 'k')) {
      e.preventDefault()
      showCmdPalette.value = !showCmdPalette.value
      return
    }
    if (e.key === '/' && !isInputFocused) {
      e.preventDefault()
      showCmdPalette.value = true
      return
    }
    // 数字键 1-9 快速切换 tab(在非输入框中)
    if (!isInputFocused && !e.ctrlKey && !e.metaKey && !e.altKey && /^[1-9]$/.test(e.key)) {
      const tab = TAB_ROUTES[Number(e.key) - 1]
      if (tab) router.push(tab.path)
    }
  })
})

// ============================================================
</script>
