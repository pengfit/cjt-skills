<template>
  <div class="compare-panel">
    <!-- 筛选条 -->
    <div class="compare-filter-bar">
      <div class="filter-group-breed">
        <label class="filter-label">
          品种
          <button class="browse-tree-btn" @click="openTreeDrawer" title="按分类体系浏览">
            📂 按分类浏览
          </button>
        </label>
        <input
          v-model="breedInput"
          type="text"
          class="breed-input"
          placeholder="输入品种名（如：热轧带肋钢筋、HRB400、商品混凝土）"
          @keydown.enter="doCompare"
        />

        <!-- NORM 跨城归一品种候选（deepext NORM 索引，与 breed-recommend 互补） -->
        <div v-if="normCompareCandidates.length" class="norm-compare-box">
          <span class="norm-compare-title">🌐 跨城归一品种（{{ normCompareCandidates.length }}）</span>
          <div class="norm-compare-list">
            <div
              v-for="(c, idx) in normCompareCandidates.slice(0, 12)"
              :key="c.normalized_breed + '_c'"
              class="norm-compare-item"
              :title="c.cities.map(x => x.label + ':' + x.docs).join(' | ')"
              @click="pickNormCompare(c)"
            >
              <span class="norm-compare-breed">{{ c.normalized_breed }}</span>
              <span class="norm-compare-meta">{{ c.cities.length }} 城 · {{ c.total_docs }}</span>
            </div>
          </div>
        </div>

        <!-- B 方案推荐区：分类标注 + 同 L3 推荐 -->
        <div v-if="recommendLoading" class="recommend-hint">
          <span class="loading-spinner"></span> 推荐中…
        </div>
        <div v-else-if="breedRecommend && breedRecommend.classifications" class="recommend-box">
          <div class="classify-card">
            <span class="classify-icon">🏷️</span>
            <span class="classify-l3">
              <strong>{{ breedRecommend.classifications.l3_code }}</strong>
              {{ breedRecommend.classifications.name_l1 }} / {{ breedRecommend.classifications.name_l2 }} / <em>{{ breedRecommend.classifications.name_l3 }}</em>
            </span>
            <span v-if="breedRecommend.classifications.gb_50500" class="classify-gb">GB {{ breedRecommend.classifications.gb_50500 }}</span>
            <span v-if="breedRecommend.siblings_total" class="classify-siblings">
              同章节 <strong>{{ breedRecommend.siblings_total }}</strong> 个品种
            </span>
          </div>
          <div v-if="breedRecommend.breeds.length" class="recommend-list">
            <span
              v-for="r in breedRecommend.breeds.slice(0, 12)"
              :key="r.breed_clean"
              class="recommend-chip"
              :title="r.breed_clean + ' | L3=' + r.l3 + ' | conf=' + r.confidence"
              @click="pickBreed(r.breed_clean)"
            >
              {{ r.breed_clean }}
              <small v-if="r.city_count > 0" class="chip-city">{{ r.city_count }}城</small>
            </span>
            <span v-if="breedRecommend.breeds.length > 12" class="recommend-more">
              还有 {{ breedRecommend.breeds.length - 12 }} 个 →
            </span>
          </div>
          <div v-if="breedRecommend.coverage_note" class="recommend-note">
            ⚠️ {{ breedRecommend.coverage_note }}
          </div>
        </div>

        <!-- 保持兼容：旧 breedSuggestions 仍能渲染 -->
        <div v-if="breedSuggestions.length && !breedRecommend" class="suggestions">
          <span
            v-for="s in breedSuggestions"
            :key="s"
            class="suggestion-chip"
            @click="pickBreed(s)"
          >{{ s }}</span>
        </div>
      </div>
      <div class="filter-group-cities">
        <label class="filter-label">
          城市（多选，最多 6 个） <span class="city-count">{{ selectedCities.length }}/6</span>
        </label>
        <div class="city-chip-row">
          <span
            v-for="o in cityOptions"
            :key="o.key"
            class="city-chip"
            :class="{ active: selectedCities.includes(o.key) }"
            :style="{ '--chip-color': o.color }"
            @click="toggleCity(o.key)"
          >{{ o.label }}</span>
        </div>
      </div>
      <div class="filter-group-row">
        <div class="filter-mini">
          <label class="filter-mini-label">单位（约束，可选）</label>
          <select v-model="unitConstraint" class="filter-select">
            <option value="">不限</option>
            <option v-for="u in commonUnits" :key="u" :value="u">{{ u }}</option>
          </select>
        </div>
        <div class="filter-mini">
          <label class="filter-mini-label">期数</label>
          <select v-model.number="periods" class="filter-select">
            <option :value="6">最近 6 期</option>
            <option :value="12">最近 12 期</option>
            <option :value="24">最近 24 期</option>
            <option :value="36">最近 36 期</option>
          </select>
        </div>
        <div class="filter-mini">
          <label class="filter-mini-label">Top spec/城</label>
          <select v-model.number="topSpecs" class="filter-select">
            <option :value="1">1</option>
            <option :value="2">2</option>
            <option :value="3">3</option>
            <option :value="5">5</option>
            <option :value="8">8</option>
          </select>
        </div>
        <button
          class="btn-compare"
          :disabled="loading || !breedInput.trim() || selectedCities.length === 0"
          @click="doCompare"
        >
          {{ loading ? '加载中…' : '开始对比' }}
        </button>
      </div>
    </div>

    <!-- 错误 -->
    <div v-if="error" class="compare-error">
      <span class="error-icon">⚠️</span>
      <span>{{ error }}</span>
      <button class="btn-retry" @click="doCompare">重试</button>
    </div>

    <!-- 空状态 -->
    <div v-if="!breedInput.trim() && !data" class="empty-hint">
      <div class="empty-icon">🔍</div>
      <div class="empty-text">输入品种名 + 选若干城市 → 看跨城价格走势对比</div>
      <div v-if="topBreedsByCity.length" class="quick-breeds">
        <div class="quick-breeds-label">热门品种（按出现城市数倒序）：</div>
        <div class="quick-breeds-row">
          <span
            v-for="b in topBreedsByCity.slice(0, 12)"
            :key="b.breed"
            class="quick-breed-chip"
            :title="`覆盖 ${b.city_count} 个城市`"
            @click="quickFill(b.breed)"
          >{{ b.breed }} <small>({{ b.city_count }}城)</small></span>
        </div>
      </div>
    </div>

    <!-- 主视图 -->
    <div v-if="data && data.ok" class="compare-content">
      <!-- 单位冲突警告（跨城均价对比失真警告） -->
      <div v-if="unitConflict" class="unit-conflict-warning">
        <span class="warn-icon">⚠️</span>
        <span class="warn-text">
          跨城单位不一致：
          <strong v-for="(uc, i) in unitConflict" :key="uc.unit">
            <template v-if="i > 0"> · </template>
            <span>{{ uc.cities.join('、') }}</span> 用 <em>{{ uc.unit }}</em>
          </strong>。
          <span class="warn-tip">同业均价对比可能失真，建议上方“单位”下拉显式约束、或退选冲突城市。</span>
        </span>
      </div>

      <!-- 关键统计：流式一行（pill + dot city） -->
      <div class="summary-bar">
        <span class="sum-pill">
          <span class="sum-emoji">📅</span>
          <strong>{{ data.aligned_periods.length }}</strong> 期对齐
        </span>
        <span class="sum-pill">
          <span class="sum-emoji">📦</span>
          共 <strong>{{ summaryTotal.docs.toLocaleString() }}</strong> 样本 / {{ summaryTotal.spec_groups }} spec
        </span>
        <span class="sum-sep" aria-hidden="true">|</span>
        <template v-for="s in data.series" :key="s.city">
          <span class="sum-city" :class="{ 'sum-city-empty': !s.n_total }">
            <span class="city-dot" :style="{ background: s.color }"></span>
            <strong>{{ s.label }}</strong>
            <span class="sum-price">
              <template v-if="s.n_total">{{ latestPrice(s) ?? '—' }}<small>{{ s.unit_used || '' }}</small></template>
              <template v-else>—</template>
            </span>
            <small v-if="s.n_total" class="sum-meta">
              {{ s.n_total }} 样本 · {{ s.spec_groups.length }} spec
              <em v-if="s.missing_periods.length">漏 {{ s.missing_periods.length }}</em>
            </small>
          </span>
        </template>
      </div>

      <!-- spec 选择（多选，按城市分别用 first spec） -->
      <div v-if="commonSpecKeys.length" class="spec-bar">
        <span class="spec-label">📐 公共规格（同 spec_key 跨城绘线，可多选）：</span>
        <span
          v-for="sk in commonSpecKeys"
          :key="sk.key"
          class="spec-chip"
          :class="{ active: selectedSpecKeys.has(sk.key) }"
          :title="`${sk.total} 样本`"
          @click="toggleSpecKey(sk.key)"
        >{{ sk.label }} <small>({{ sk.total }})</small></span>
        <span class="spec-bar-hint">{{ selectedSpecKeys.size }} / {{ commonSpecKeys.length }} 选中</span>
      </div>

      <!-- 主图：每个 spec_key 一个独立 ECharts 实例 -->
      <div class="compare-card">
        <div v-if="!subChartGroups.length" class="compare-empty">无 spec_key 可绘</div>
        <div v-else class="compare-charts-grid" :style="layoutStyle">
          <div
            v-for="(g, idx) in subChartGroups"
            :key="g.spec_key"
            class="compare-chart-cell"
          >
            <div class="cell-header">
              <span class="cell-seq">{{ idx + 1 }}/{{ subChartGroups.length }}</span>
              <span class="cell-title" :title="g.spec_label">
                {{ g.spec_label.length > 18 ? g.spec_label.slice(0, 18) + '…' : g.spec_label }}
              </span>
              <span class="cell-align" :class="`align-${g.align_method}`" :title="`对齐方式：${g.align_method}`">
                [{{ g.align_method }}]
              </span>
            </div>
            <div
              class="cell-chart"
              :ref="el => setChartRef(el, idx)"
            ></div>
          </div>
        </div>
      </div>

      <!-- 价差走势：跨城 max/min + spread% （P0-#3） -->
      <SectionHeader
        v-if="canShowSpreadSection"
        title="价差走势（跨城 max/min + spread%）"
        dot-color="orange"
        :subtitle="spreadSubtitle"
      >
        <template #right>
          <div v-if="spreadHasData" class="export-bar">
            <button class="export-btn" @click="onExportSpreadPng" title="导出价差走势图 PNG">📸 PNG</button>
            <button class="export-btn" @click="onExportCompareCsv" title="导出跨城同期价对比 + 价差为 CSV">📊 CSV</button>
          </div>
        </template>
      </SectionHeader>
      <div v-if="canShowSpreadSection" class="spread-card">
        <div v-if="!spreadHasData" class="compare-empty">
          <div class="empty-title">{{ spreadEmptyTitle }}</div>
          <div class="empty-detail">{{ spreadEmptyDetail }}</div>
        </div>
        <div v-else ref="spreadChartEl" class="spread-chart"></div>
        <div v-if="spreadHasData && spreadLatest" class="spread-quick">
          <span class="spread-quick-pill">
            <span class="sp-emoji">📍</span> 最新一期 <strong>{{ spreadLatest.label }}</strong>
          </span>
          <span class="spread-quick-pill">
            🔺 最高 <strong>{{ cityLabelOf(spreadLatest.max_city) }}</strong>
            <span class="sp-val">{{ spreadLatest.max }}</span>
          </span>
          <span class="spread-quick-pill">
            🔻 最低 <strong>{{ cityLabelOf(spreadLatest.min_city) }}</strong>
            <span class="sp-val">{{ spreadLatest.min }}</span>
          </span>
          <span class="spread-quick-pill" :class="spreadSeverityClass(spreadLatest.spread_pct)">
            📏 价差 <strong>{{ spreadLatest.spread }}</strong>
            <em class="sp-pct">{{ spreadLatest.spread_pct.toFixed(1) }}%</em>
          </span>
        </div>
      </div>

      <!-- 同期对比表 -->
      <SectionHeader title="同期价对比表（按周期对齐）" dot-color="blue" :subtitle="`每个城市在每个对齐期的均价`" />
      <div class="period-table-scroll">
        <table class="period-table">
          <thead>
            <tr>
              <th class="th-period">周期</th>
              <th
                v-for="s in data.series"
                :key="s.city"
                :style="{ color: s.color }"
                class="th-city"
              >{{ s.label }} <small v-if="s.unit_used">({{ s.unit_used }})</small></th>
              <th class="th-spread">价差区间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, idx) in data.aligned_periods" :key="p.start">
              <td class="td-period">{{ p.label }}</td>
              <td v-for="s in data.series" :key="s.city" class="td-price" :class="{ missing: missingForCityPeriod(s, p.start) }">
                <template v-if="getPriceFor(s, p.start) != null">
                  <div class="price-val" :style="{ color: s.color }">{{ getPriceFor(s, p.start).toFixed(2) }}</div>
                  <div class="price-meta">n={{ getPriceForCount(s, p.start) }}</div>
                </template>
                <span v-else class="no-data">—</span>
              </td>
              <td class="td-spread">
                <template v-if="spreadFor(p.start)">
                  <span class="spread-val">{{ spreadFor(p.start).min.toFixed(2) }} – {{ spreadFor(p.start).max.toFixed(2) }}</span>
                  <span class="spread-pct" :class="spreadClass(p.start)">
                    {{ spreadFor(p.start).spread_pct.toFixed(1) }}%
                  </span>
                </template>
                <span v-else class="no-data">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 每城市 spec 明细（折叠区） -->
      <SectionHeader
        title="各城市规格明细（spec 拆分）"
        dot-color="green"
        :subtitle="`每个城市的 top ${topSpecs} 个 spec，及其按时序的 min/max/avg`"
      />
      <div class="city-detail-grid">
        <div v-for="s in data.series" :key="s.city" class="city-detail" :style="{ '--accent': s.color }">
          <div class="city-detail-head" :style="{ background: s.color }">
            <span class="city-name">{{ s.label }}</span>
            <span class="city-meta">
              <em v-if="s.unit_fallback" :title="`'${s.unit_used}' 非用户指定，按样本数自动选取`">自动</em>
              {{ s.n_total }} 样本
              <small v-if="s.missing_periods.length" class="missing-tag">漏 {{ s.missing_periods.length }} 期</small>
            </span>
          </div>
          <div v-if="!s.spec_groups.length" class="city-empty">该城市无数据</div>
          <table v-else class="city-spec-table">
            <thead>
              <tr>
                <th>规格</th>
                <th v-for="p in data.aligned_periods" :key="p.start" :title="p.label">
                  {{ p.start.slice(5) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="sg in s.spec_groups" :key="sg.spec_key">
                <td class="td-spec-label" :title="sg.spec_label">
                  {{ sg.spec_label }} <small class="align-tag align-{{ sg.align_method }}">{{ sg.align_method }}</small>
                </td>
                <td v-for="p in data.aligned_periods" :key="p.start" class="td-spec-price">
                  <template v-if="getSpecPt(sg, p.start)">
                    <div class="sp-val">{{ getSpecPt(sg, p.start).avg.toFixed(0) }}</div>
                    <div class="sp-meta">{{ getSpecPt(sg, p.start).min }}~{{ getSpecPt(sg, p.start).max }} · n={{ getSpecPt(sg, p.start).n }}</div>
                  </template>
                  <span v-else class="no-data">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- C 方案：分类树抽屉 -->
    <Teleport to="body">
      <div v-if="treeDrawerOpen" class="tree-drawer-mask" @click.self="treeDrawerOpen = false">
        <div class="tree-drawer">
          <div class="tree-drawer-head">
            <h3>📂 按分类体系浏览品种</h3>
            <button class="tree-close" @click="treeDrawerOpen = false">✕</button>
          </div>
          <div v-if="!treeData" class="tree-loading">加载分类树…</div>
          <div v-else class="tree-body">
            <div class="tree-stats">
              {{ treeData.l1_count }} L1 / {{ treeData.l2_count }} L2 / {{ treeData.l3_count }} L3 · 共 <strong>{{ treeData.breed_total }}</strong> 个品种
            </div>
            <div class="tree-list">
              <div v-for="l1 in treeData.tree" :key="l1.code" class="tree-node tree-l1">
                <div class="tree-node-row" @click="toggleTreeNode(l1.code)">
                  <span class="tree-toggle">{{ treeExpanded[l1.code] ? '▼' : '▶' }}</span>
                  <span class="tree-code">{{ l1.code }}</span>
                  <span class="tree-name">{{ l1.name }}</span>
                  <span class="tree-meta">L2 {{ l1.l2_count }} · 品种 {{ l1.breed_count }}</span>
                </div>
                <div v-if="treeExpanded[l1.code]" class="tree-children">
                  <div v-for="l2 in l1.l2_list" :key="l2.code" class="tree-node tree-l2">
                    <div class="tree-node-row" @click.stop="toggleTreeNode(l2.code)">
                      <span class="tree-toggle">{{ treeExpanded[l2.code] ? '▼' : '▶' }}</span>
                      <span class="tree-code">{{ l2.code }}</span>
                      <span class="tree-name">{{ l2.name }}</span>
                      <span class="tree-meta">L3 {{ l2.l3_count }} · 品种 {{ l2.breed_count }}</span>
                    </div>
                    <div v-if="treeExpanded[l2.code]" class="tree-children">
                      <div v-for="l3 in l2.l3_list" :key="l3.code" class="tree-node tree-l3">
                        <div class="tree-node-row" @click.stop="toggleTreeNode(l3.code)">
                          <span class="tree-toggle">{{ treeExpanded[l3.code] ? '▼' : '▶' }}</span>
                          <span class="tree-code">{{ l3.code }}</span>
                          <span class="tree-name">{{ l3.name }}</span>
                          <span class="tree-meta">品种 {{ l3.breed_count }}</span>
                        </div>
                        <div v-if="treeExpanded[l3.code]" class="tree-l3-breeds">
                          <button
                            v-if="l3.breed_count > 0"
                            class="tree-l3-btn"
                            @click.stop="pickL3(l3.code)"
                          >📦 看该 L3 下 {{ l3.breed_count }} 个品种</button>
                          <span v-else class="tree-l3-empty">该 L3 下尚无品种</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, onBeforeUnmount } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'
import SectionHeader from './SectionHeader.vue'
import { exportChartAsPng, exportCsvAsFile, withTimestamp } from '../composables/useExport.js'

const API = import.meta.env.VITE_API_URL || '/api'

// 状态
const breedInput = ref('热轧带肋钢筋')      // 默认值便于演示
const breedSuggestions = ref([])
const cityOptions = ref([])                  // 全部可用城市
const selectedCities = ref([])               // 选中城市
const unitConstraint = ref('')                // 单位约束
const periods = ref(6)
const topSpecs = ref(3)
const loading = ref(false)
const error = ref('')
const data = ref(null)                        // API 返回

// 多子图：小 multiples，每个 spec_key 一个独立 echarts 实例
const chartCells = ref([])                    // DOM ref 数组（索引 → cell div）
const chartInstances = new Map()              // 索引 → echarts 实例
function setChartRef(el, idx) {
  if (el) chartCells.value[idx] = el
  else chartCells.value[idx] = null
}

// 价差走势图：单一 ECharts 实例，双 y 轴（价格左 + spread%右）
const spreadChartEl = ref(null)
let spreadChartInstance = null

const commonUnits = ref(['t', 'm', 'kg', 'm³', 'm²', '根', '只', '块'])
const topBreedsByCity = ref([])               // 用于空状态热门品种

// 用户选的 spec_key
const selectedSpecKeys = ref(new Set())

// B 方案：品种推荐 (品种 → 同 L3 + 跨城覆盖度)
const breedRecommend = ref(null)              // /api/stats/breed-recommend 返回
const recommendLoading = ref(false)

// C 方案：分类树抽屉
const treeData = ref(null)                    // /api/stats/category-tree 返回
const treeDrawerOpen = ref(false)
const treeExpanded = ref({})                  // 展开状态 {l1|l2|l3: true}

// 颜色分配（每城市一条线）— 与 API 返回 color 同步
const COLOR_POOL_OVERRIDE = {}

// small multiples 上限（每个 spec_key 一张子图；>此值会被提示"图表拥挤"）
const MAX_SMALL_MULTIPLES = 4

// 计算属性
const selectedCityCfgs = computed(() =>
  cityOptions.value.filter(c => selectedCities.value.includes(c.key))
)

// 跨城单位冲突检测：不同城市出现 ≥2 种 unit_used 时报警（均价对比失真）
const unitConflict = computed(() => {
  if (!data.value?.series?.length) return null
  const usage = new Map()  // unit -> cities[]
  for (const s of data.value.series) {
    if (!s.unit_used) continue
    if (!usage.has(s.unit_used)) usage.set(s.unit_used, [])
    usage.get(s.unit_used).push(s.label)
  }
  if (usage.size <= 1) return null
  return [...usage.entries()].map(([unit, cities]) => ({ unit, cities }))
})

// 跨城公共规格（同 spec_key 在 ≥ 2 城市出现）
const commonSpecKeys = computed(() => {
  if (!data.value) return []
  const counts = new Map()  // spec_key -> { label, total }
  for (const s of data.value.series) {
    for (const sg of s.spec_groups) {
      if (!selectedSpecKeys.value.size || selectedSpecKeys.value.has(sg.spec_key)) {
        const cur = counts.get(sg.spec_key) || { label: sg.spec_label, total: 0, cities: 0 }
        cur.total += sg.n_total
        cur.cities += 1
        counts.set(sg.spec_key, cur)
      }
    }
  }
  const arr = []
  for (const [key, info] of counts) {
    arr.push({ key, label: info.label, total: info.total, cities: info.cities })
  }
  // 优先按城市数，再按样本数
  arr.sort((a, b) => (b.cities - a.cities) || (b.total - a.total))
  return arr
})

// 子图分组：每个 spec_key 一组，含该 spec 在各城市的点列
const subChartGroups = computed(() => {
  if (!data.value?.aligned_periods?.length) return []
  const selected = selectedSpecKeys.value.size === 0
    ? new Set(data.value.series.flatMap(s => s.spec_groups.map(g => g.spec_key)))
    : selectedSpecKeys.value
  const groupsBySpec = new Map()
  for (const s of data.value.series) {
    for (const sg of s.spec_groups) {
      if (!selected.has(sg.spec_key)) continue
      if (!groupsBySpec.has(sg.spec_key)) {
        groupsBySpec.set(sg.spec_key, {
          spec_key: sg.spec_key,
          spec_label: sg.spec_label,
          align_method: sg.align_method,
          period_labels: data.value.aligned_periods.map(p => p.label),
          cities: [],
        })
      }
      const g = groupsBySpec.get(sg.spec_key)
      g.cities.push({
        city: s.city,
        label: s.label,
        color: s.color,
        points: data.value.aligned_periods.map(p => {
          const pt = sg.points.find(pt => pt.period_start === p.start)
          return pt ? { value: pt.avg, avg: pt.avg, min: pt.min, max: pt.max, n: pt.n } : null
        }),
      })
    }
  }
  return [...groupsBySpec.values()]
})

// 网格布局：按子图数选列数、各行高（包含 header + chart 合计）
const HEADER_H = 34
const layoutStyle = computed(() => {
  const N = subChartGroups.value.length
  let cols, chartH
  if (N === 1)      { cols = 1; chartH = 360 }
  else if (N === 2) { cols = 2; chartH = 280 }
  else if (N === 3) { cols = 1; chartH = 200 }
  else if (N === 4) { cols = 2; chartH = 220 }   // 2×2
  else              { cols = 1; chartH = 140 }
  return {
    gridTemplateColumns: `repeat(${cols}, 1fr)`,
    gridAutoRows: `${chartH + HEADER_H}px`,
  }
})

// 汇总统计：所有城市合计样本与 spec_group 数
const summaryTotal = computed(() => {
  if (!data.value?.series) return { docs: 0, spec_groups: 0 }
  let docs = 0, sg = 0
  for (const s of data.value.series) {
    docs += s.n_total || 0
    sg += (s.spec_groups?.length || 0)
  }
  return { docs, spec_groups: sg }
})

// ── 方法 ──
async function loadCityOptions() {
  try {
    const { data: d } = await axios.get(`${API}/skill-registry`)
    cityOptions.value = (d?.skills || [])
      .filter(s => s.dws_index)  // 只要有 DWS 索引的
      .map(s => {
        // 用省份色（如无则灰）
        const colors = {
          '陕西':'#dc2626', '四川':'#2563eb', '重庆':'#16a34a',
          '山东':'#ea580c', '河南':'#7c3aed', '湖南':'#0891b2',
          '江西':'#db2777', '宁夏':'#65a30d', '青海':'#9333ea',
          '新疆':'#0d9488', '内蒙古':'#e11d48', '海南':'#4f46e5',
        }
        return {
          key: s.key,
          label: s.label || s.key,
          province: s.province || '',
          color: colors[s.province] || colors[s.label] || '#64748b',
        }
      })
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
    // 默认选前 2 个 DWS 存在的城市
    if (!selectedCities.value.length) {
      const withDws = cityOptions.value.filter(c => c.key === 'hainan' || c.key === 'chongqing')
      selectedCities.value = withDws.slice(0, 2).map(c => c.key) || cityOptions.value.slice(0, 2).map(c => c.key)
    }
    await loadTopBreeds()
  } catch (e) {
    error.value = '加载城市列表失败：' + e.message
  }
}

async function loadTopBreeds() {
  // 用 search 拉高频品种（粗略；实际跨城要 JOIN，但 MVP 用搜索代替）
  try {
    const { data: d } = await axios.get(`${API}/search?page=1&page_size=20`)
    const breeds = d?.data || []
    // 按品种名汇总（province 数 + 文档数）
    const byBreed = new Map()
    for (const h of breeds) {
      const k = h.breed
      if (!byBreed.has(k)) byBreed.set(k, { breed: k, count: 0, provinces: new Set() })
      const cur = byBreed.get(k)
      cur.count += 1
      if (h.province) cur.provinces.add(h.province)
    }
    const arr = [...byBreed.values()].map(v => ({
      ...v, provinces: undefined, city_count: v.provinces.size,
    }))
    arr.sort((a, b) => (b.city_count - a.city_count) || (b.count - a.count))
    topBreedsByCity.value = arr
  } catch (e) {
    console.warn('loadTopBreeds failed:', e)
  }
}

function toggleCity(key) {
  const i = selectedCities.value.indexOf(key)
  if (i >= 0) selectedCities.value.splice(i, 1)
  else if (selectedCities.value.length < 6) selectedCities.value.push(key)
}

function quickFill(breed) {
  breedInput.value = breed
  doCompare()
}

function pickBreed(s) {
  breedInput.value = s
  breedSuggestions.value = []
  // 填完后重新拉一次推荐（可能选出同 L3 其他品种）
  loadBreedRecommend(s)
}

// ── 跨城 NORM 候选（与 breed-recommend 互补，供跨城统一品种使用） ──
const normCompareCandidates = ref([])
let _normCompareTimer = null

watch(breedInput, (v) => {
  if (_normCompareTimer) clearTimeout(_normCompareTimer)
  const kw = (v || '').trim()
  if (!kw) { normCompareCandidates.value = []; return }
  _normCompareTimer = setTimeout(async () => {
    try {
      const { data: d } = await axios.get(`${API}/norm/breeds/search`, {
        params: { keyword: kw, limit: 12 },
      })
      normCompareCandidates.value = d.ok ? (d.results || []) : []
    } catch {
      normCompareCandidates.value = []
    }
  }, 300)
})

function pickNormCompare(c) {
  breedInput.value = c.normalized_breed
  // 触发分类推荐，验证品种分类位置
  loadBreedRecommend(c.normalized_breed)
}

onBeforeUnmount(() => {
  if (_normCompareTimer) clearTimeout(_normCompareTimer)
})

// ── B 方案：品种推荐 ──
let _recommendDebounce = null
function loadBreedRecommend(keyword) {
  clearTimeout(_recommendDebounce)
  const kw = (keyword || '').trim()
  if (!kw) {
    breedRecommend.value = null
    return
  }
  _recommendDebounce = setTimeout(async () => {
    recommendLoading.value = true
    try {
      const { data: d } = await axios.get(`${API}/stats/breed-recommend`, {
        params: { keyword: kw, limit: 30, min_confidence: 0.9 },
      })
      if (!d.ok) throw new Error(d.error || '推荐服务异常')
      breedRecommend.value = d
    } catch (e) {
      breedRecommend.value = null
      console.warn('loadBreedRecommend failed:', e.message)
    } finally {
      recommendLoading.value = false
    }
  }, 300)
}

// ── C 方案：分类树 ──
async function openTreeDrawer() {
  treeDrawerOpen.value = true
  if (!treeData.value) {
    try {
      const { data: d } = await axios.get(`${API}/stats/category-tree`)
      if (!d.ok) throw new Error(d.error || '分类树加载失败')
      treeData.value = d
    } catch (e) {
      console.warn('loadCategoryTree failed:', e.message)
    }
  }
}

function toggleTreeNode(key) {
  treeExpanded.value = { ...treeExpanded.value, [key]: !treeExpanded.value[key] }
}

function pickL3(l3Code) {
  // 点 L3 下的“看该 L3 下 N 个品种”→ 调推荐（不传 keyword）
  treeDrawerOpen.value = false
  recommendLoading.value = true
  breedRecommend.value = null
  axios.get(`${API}/stats/breed-recommend`, {
    params: { l3: l3Code, limit: 30, min_confidence: 0.9 },
  }).then(({ data: d }) => {
    if (!d.ok) throw new Error(d.error || '推荐异常')
    breedRecommend.value = d
    // 自动填充第一个品种名到输入框
    if (d.breeds && d.breeds.length) {
      breedInput.value = d.breeds[0].breed_clean
    }
  }).catch((e) => {
    console.warn('pickL3 recommend failed:', e.message)
  }).finally(() => {
    recommendLoading.value = false
  })
}

async function doCompare() {
  if (!breedInput.value.trim() || selectedCities.value.length === 0) return
  loading.value = true
  error.value = ''
  try {
    const url = `${API}/stats/price-trend-compare?` +
      new URLSearchParams({
        breed: breedInput.value.trim(),
        cities: selectedCities.value.join(','),
        unit: unitConstraint.value || '',
        periods: String(periods.value),
        top_specs: String(topSpecs.value),
      })
    const { data: d } = await axios.get(url)
    if (!d.ok) throw new Error(d.error || 'API 返回错误')
    data.value = d
    // 默认选 top MAX_SMALL_MULTIPLES 个公共 spec_key（按跨城覆盖数 → 样本数倒序）
    const _sk_counter = new Map()
    for (const s of d.series) {
      for (const g of s.spec_groups) {
        const cur = _sk_counter.get(g.spec_key) || { label: g.spec_label, cities: 0, total: 0 }
        cur.cities += 1
        cur.total += g.n_total
        _sk_counter.set(g.spec_key, cur)
      }
    }
    const _top_spec = [..._sk_counter.entries()]
      .map(([key, v]) => ({ key, ...v }))
      .sort((a, b) => (b.cities - a.cities) || (b.total - a.total))
      .slice(0, MAX_SMALL_MULTIPLES)
    selectedSpecKeys.value = new Set(_top_spec.map(s => s.key))
    await nextTick()
    renderAllCharts()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function toggleSpecKey(key) {
  const s = new Set(selectedSpecKeys.value)
  if (s.has(key)) s.delete(key); else s.add(key)
  selectedSpecKeys.value = s
  // 不重新发 API，前端过滤即可
  renderAllCharts()
}

// 视图工具
function latestPrice(s) {
  // 取该城市最大的 spec 在最近一期的价格
  if (!s.spec_groups.length) return null
  const all_pts = s.spec_groups.flatMap(g => g.points)
  if (!all_pts.length) return null
  all_pts.sort((a, b) => (a.period_start < b.period_start ? 1 : -1))
  const last = all_pts[0].avg
  if (Math.abs(last) >= 1000) return last.toFixed(0)
  return last.toFixed(2)
}

function getPriceFor(s, periodStart) {
  if (!s.spec_groups.length) return null
  const pts = s.spec_groups.flatMap(g => g.points).filter(p => p.period_start === periodStart)
  if (!pts.length) return null
  const sum = pts.reduce((acc, p) => acc + p.avg * p.n, 0)
  const cnt = pts.reduce((acc, p) => acc + p.n, 0)
  return cnt ? sum / cnt : null
}

function getPriceForCount(s, periodStart) {
  if (!s.spec_groups.length) return 0
  return s.spec_groups.flatMap(g => g.points).filter(p => p.period_start === periodStart).reduce((acc, p) => acc + p.n, 0)
}

function missingForCityPeriod(s, periodStart) {
  return s.missing_periods.includes(periodStart)
}

function spreadFor(periodStart) {
  // 价差区间 + spread%
  const prices = []
  for (const s of data.value.series) {
    const p = getPriceFor(s, periodStart)
    if (p != null) prices.push({ city: s.label, price: p, color: s.color })
  }
  if (prices.length < 2) return null
  const vals = prices.map(p => p.price)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const mid = vals.reduce((a, b) => a + b, 0) / vals.length
  return {
    min, max,
    spread_pct: mid ? ((max - min) / mid) * 100 : 0,
    cities: prices,
  }
}

function spreadClass(periodStart) {
  const s = spreadFor(periodStart)
  if (!s) return ''
  if (s.spread_pct >= 20) return 'spread-huge'
  if (s.spread_pct >= 5) return 'spread-mid'
  return 'spread-low'
}

function getSpecPt(sg, periodStart) {
  return sg.points.find(p => p.period_start === periodStart)
}

// ── 导出（P1-#6）：PNG = 当前价差走势；CSV = 跨城同期价对比 + 价差 ──
function onExportSpreadPng() {
  if (!spreadChartInstance) {
    console.warn('[export] no spread chart instance')
    return
  }
  const cities = (data.value?.cities || []).map(c => c.label).join('-')
  const fname = `${withTimestamp(`${breedInput.value}-${cities}-价差`)}.png`
  exportChartAsPng(spreadChartInstance, fname)
}

function onExportCompareCsv() {
  if (!data.value?.series?.length) return
  const rows = []
  // 表头：周期 | <每城: 城市名(单位)_均价> | max | min | spread | spread%
  const cityHeaders = data.value.series.map(s => `${s.label}${s.unit_used ? `(${s.unit_used})` : ''}`)
  rows.push(['周期', ...cityHeaders, '最高价', '最高价城市', '最低价', '最低价城市', '价差', 'spread%'])
  const spByPeriod = new Map((data.value?.spread?.by_period || []).map(p => [p.period_start, p]))
  for (const p of data.value.aligned_periods) {
    const cells = data.value.series.map(s => {
      const v = getPriceFor(s, p.start)
      return v == null ? '' : v.toFixed(2)
    })
    const sp = spByPeriod.get(p.start)
    rows.push([
      p.label,
      ...cells,
      sp?.max ?? '',
      sp ? cityLabelOf(sp.max_city) : '',
      sp?.min ?? '',
      sp ? cityLabelOf(sp.min_city) : '',
      sp?.spread ?? '',
      sp?.spread_pct != null ? sp.spread_pct.toFixed(2) + '%' : '',
    ])
  }
  const cities = (data.value?.cities || []).map(c => c.label).join('-')
  exportCsvAsFile(rows, `${withTimestamp(`${breedInput.value}-${cities}-对比`)}.csv`)
}

// ── 多子图渲染：每个 spec_key 一个独立 ECharts 实例 ──
function buildSubChartOption(g) {
  const alignColor = g.align_method === 'attr' ? '#1d4ed8'
    : g.align_method === 'spec_norm' ? '#a16207'
    : '#94a3b8'
  const series = g.cities.map(pbc => ({
    name: `${pbc.label} · ${g.spec_label}`,
    type: 'line',
    data: pbc.points,
    smooth: false,
    symbol: 'circle',
    symbolSize: 4,
    lineStyle: { width: 1.5, color: pbc.color },
    itemStyle: { color: pbc.color },
    emphasis: { focus: 'series' },
    connectNulls: true,
  }))
  return {
    // 标题改由 HTML header 渲染，避免与 grid 内容重叠
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.98)',
      borderColor: '#cbd5e1',
      textStyle: { color: '#0f172a' },
      formatter: (params) => {
        if (!params?.length) return ''
        const head = params[0]?.axisValue || ''
        let html = `<b>${head}</b><br/>`
        for (const p of params) {
          const d = p.data
          if (!d) { html += `${p.marker} ${p.seriesName}: <em>无数据</em><br/>`; continue }
          const v = d.avg.toFixed(2)
          html += `${p.marker} ${p.seriesName}: <b>${v}</b> <small>(min ${d.min} – max ${d.max})</small><br/>`
        }
        return html
      },
    },
    legend: {
      bottom: 0,
      type: 'scroll',
      textStyle: { color: '#475569', fontSize: 10 },
      itemHeight: 10,
    },
    grid: { left: 50, right: 16, top: 28, bottom: 36 },
    xAxis: {
      type: 'category',
      data: g.period_labels,
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false },
      axisLabel: { color: '#94a3b8', fontSize: 9, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#94a3b8', fontSize: 9 },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series,
  }
}

function renderAllCharts() {
  const groups = subChartGroups.value
  // 释放多余实例
  for (const [idx, inst] of chartInstances) {
    if (idx >= groups.length) {
      try { inst.dispose() } catch {}
      chartInstances.delete(idx)
    }
  }
  groups.forEach((g, idx) => {
    const el = chartCells.value[idx]
    if (!el) return
    let inst = chartInstances.get(idx)
    if (!inst) {
      inst = echarts.init(el)
      chartInstances.set(idx, inst)
      window.addEventListener('resize', () => inst && inst.resize())
    }
    inst.setOption(buildSubChartOption(g), true)
  })
  // 价差走势图
  renderSpreadChart()
}

// ── 价差走势图（P0-#3） ──
function _cityColorByKey(key) {
  const s = data.value?.series?.find(s => s.city === key)
  return s?.color || '#94a3b8'
}
function cityLabelOf(key) {
  if (!key) return '—'
  const s = data.value?.series?.find(s => s.city === key)
  return s?.label || key
}
function spreadSeverityClass(pct) {
  if (pct == null) return ''
  if (pct >= 20) return 'spread-severe'
  if (pct >= 5) return 'spread-mid'
  return 'spread-low'
}
const spreadSubtitle = computed(() => {
  if (!data.value?.spread?.by_period?.length) return '跨城价差走势图（选 2 个以上城市）'
  const periods = data.value.aligned_periods?.length || 0
  return `${periods} 期 · 每期取跨城最高/最低均价，红色 max / 绿色 min · 柱状为 spread%（相对当月均值）`
})
const canShowSpreadSection = computed(() => selectedCities.value.length >= 2)
const spreadHasData = computed(() => {
  const arr = data.value?.spread?.by_period || []
  return arr.some(p => p.n_cities >= 2)
})
// 诊断空状态：不同原因分别给出提示
const spreadEmptyTitle = computed(() => {
  if (selectedCities.value.length < 2) return '至少选 2 个城市才能看价差'
  // 选了 2+ 城但仍无价差——进一步区分原因
  const series = data.value?.series || []
  const withData = series.filter(s => (s.n_total || 0) > 0).length
  const noData = series.filter(s => (s.n_total || 0) === 0).length
  if (series.length === 0) return '该品种在选中城市都无数据'
  if (withData === 0) return '该品种在选中城市都无样本'
  if (noData > 0 && withData < series.length) {
    return `${withData} 城有数据 · ${noData} 城无样本，但跨城无同期重叠`
  }
  return '跨城 spec 未对齐（公共 spec_key 为空）'
})
const spreadEmptyDetail = computed(() => {
  if (selectedCities.value.length < 2) return `当前选了 ${selectedCities.value.length} 个城市，上方多选几个 →`
  const series = data.value?.series || []
  const emptyCities = series.filter(s => (s.n_total || 0) === 0).map(s => s.label)
  const cityWith = series.filter(s => (s.n_total || 0) > 0).map(s => s.label)
  if (emptyCities.length) {
    return `无样本城市：${emptyCities.join('、')} · 有数据：${cityWith.join('、') || '无'}。试试换个品种、或退化期数`
  }
  return '可试：调大 “Top spec/城” 上限、或换品种重试'
})
const spreadLatest = computed(() => {
  const arr = data.value?.spread?.by_period || []
  // 倒序找第一个 n_cities>=2 的
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i].n_cities >= 2) return arr[i]
  }
  return null
})

function buildSpreadChartOption() {
  const arr = (data.value?.spread?.by_period || []).filter(p => p.n_cities >= 2)
  if (!arr.length) return null
  const xLabels = arr.map(p => p.label)
  // 每点携带 max_city / min_city 给 tooltip 用
  const maxData = arr.map(p => ({
    value: p.max,
    max_city: p.max_city,
    min_city: p.min_city,
    period_start: p.period_start,
  }))
  const minData = arr.map(p => ({
    value: p.min,
    max_city: p.max_city,
    min_city: p.min_city,
    period_start: p.period_start,
  }))
  const spreadData = arr.map(p => p.spread)
  const spreadPctData = arr.map(p => p.spread_pct)
  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.98)',
      borderColor: '#cbd5e1',
      textStyle: { color: '#0f172a' },
      formatter: (params) => {
        if (!params?.length) return ''
        const head = params[0].axisValue
        const idx = params[0].dataIndex
        const pt = arr[idx]
        const maxCityLabel = cityLabelOf(pt.max_city)
        const minCityLabel = cityLabelOf(pt.min_city)
        const maxColor = _cityColorByKey(pt.max_city)
        const minColor = _cityColorByKey(pt.min_city)
        let html = `<b>${head}</b> <small style="color:#94a3b8">(${pt.period_start})</small><br/>`
        const maxP = params.find(p => p.seriesName === '最高价')
        const minP = params.find(p => p.seriesName === '最低价')
        const spP = params.find(p => p.seriesName === '价差%')
        if (maxP) {
          html += `${maxP.marker} 最高价 <b style="color:${maxColor}">${maxCityLabel}</b>: <b>${pt.max}</b><br/>`
        }
        if (minP) {
          html += `${minP.marker} 最低价 <b style="color:${minColor}">${minCityLabel}</b>: <b>${pt.min}</b><br/>`
        }
        html += `<span style="display:inline-block;width:8px"></span>价差 <b>${pt.spread}</b> · <em style="color:${spreadSeverityClass(pt.spread_pct)==='spread-severe'?'#dc2626':spreadSeverityClass(pt.spread_pct)==='spread-mid'?'#d97706':'#16a34a'}">${pt.spread_pct.toFixed(1)}%</em><br/>`
        if (spP && pt.spread_pct > 0) {
          html += `${spP.marker} 价差%: ${pt.spread_pct.toFixed(1)}%<br/>`
        }
        return html
      },
    },
    legend: {
      top: 0, type: 'scroll', textStyle: { color: '#475569', fontSize: 11 },
    },
    grid: { left: 60, right: 60, top: 36, bottom: 30 },
    xAxis: {
      type: 'category',
      data: xLabels,
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisLabel: { color: '#64748b', fontSize: 10, hideOverlap: true },
    },
    yAxis: [
      {
        type: 'value',
        name: '价格',
        nameTextStyle: { color: '#64748b', fontSize: 10 },
        axisLabel: { color: '#475569', fontSize: 10 },
        splitLine: { lineStyle: { color: '#f1f5f9' } },
      },
      {
        type: 'value',
        name: 'spread %',
        nameTextStyle: { color: '#94a3b8', fontSize: 10 },
        axisLabel: { color: '#94a3b8', fontSize: 10, formatter: '{value}%' },
        splitLine: { show: false },
        max: (val) => Math.max(50, Math.ceil(val.max * 1.2)),
      },
    ],
    series: [
      {
        name: '最高价',
        type: 'line',
        data: maxData,
        smooth: false,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: '#dc2626', width: 2 },
        itemStyle: { color: '#dc2626' },
        z: 3,
      },
      {
        name: '最低价',
        type: 'line',
        data: minData,
        smooth: false,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: '#16a34a', width: 2 },
        itemStyle: { color: '#16a34a' },
        z: 3,
      },
      {
        name: '价差%',
        type: 'bar',
        yAxisIndex: 1,
        data: spreadPctData,
        barMaxWidth: 18,
        itemStyle: {
          color: (p) => {
            const v = p.value || 0
            if (v >= 20) return '#dc2626'
            if (v >= 5) return '#d97706'
            return '#16a34a'
          },
          opacity: 0.6,
        },
        z: 2,
      },
    ],
  }
}

function renderSpreadChart() {
  if (!spreadChartEl.value) {
    if (spreadChartInstance) { try { spreadChartInstance.dispose() } catch {}; spreadChartInstance = null }
    return
  }
  const opt = buildSpreadChartOption()
  if (!opt) {
    if (spreadChartInstance) { try { spreadChartInstance.dispose() } catch {}; spreadChartInstance = null }
    return
  }
  if (!spreadChartInstance) {
    spreadChartInstance = echarts.init(spreadChartEl.value)
    window.addEventListener('resize', () => spreadChartInstance && spreadChartInstance.resize())
  }
  spreadChartInstance.setOption(opt, true)
}

watch(spreadHasData, () => nextTick(renderSpreadChart))

// watch 渲染
watch(subChartGroups, () => nextTick(renderAllCharts), { deep: true })

// 生命周期
onMounted(async () => {
  await loadCityOptions()
  // 首次进入：默认品种触发一次推荐
  if (breedInput.value.trim()) {
    loadBreedRecommend(breedInput.value)
  }
})

// watch 品种输入：实时推荐（debounce 300ms）
watch(breedInput, (v) => loadBreedRecommend(v))
onBeforeUnmount(() => {
  for (const inst of chartInstances.values()) { try { inst.dispose() } catch {} }; chartInstances.clear()
  if (spreadChartInstance) { try { spreadChartInstance.dispose() } catch {}; spreadChartInstance = null }
})
</script>

<style scoped>
.compare-panel {
  padding: 4px 0 80px;
}

.compare-filter-bar {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin: 12px 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
}
.filter-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 6px;
}
.city-count {
  font-size: 10px;
  color: #94a3b8;
  margin-left: 4px;
}
.breed-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.breed-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}
.suggestions {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.suggestion-chip {
  font-size: 11px;
  padding: 2px 8px;
  background: #f1f5f9;
  color: #475569;
  border-radius: 3px;
  cursor: pointer;
}
.suggestion-chip:hover { background: #dbeafe; color: #1d4ed8; }

.city-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.city-chip {
  --chip-color: #64748b;
  display: inline-block;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  background: #f1f5f9;
  color: var(--chip-color);
  border: 1.5px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}
.city-chip:hover {
  border-color: var(--chip-color);
}
.city-chip.active {
  background: var(--chip-color);
  color: #fff;
  font-weight: 500;
}

.filter-group-row {
  grid-column: 1 / 3;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
}
.filter-mini { display: flex; flex-direction: column; }
.filter-mini-label {
  font-size: 11px;
  color: #64748b;
  margin-bottom: 2px;
}
.filter-select {
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 12px;
  background: #fff;
  color: #0f172a;
}
.btn-compare {
  margin-left: auto;
  padding: 8px 20px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-compare:hover:not(:disabled) {
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.3);
  transform: translateY(-1px);
}
.btn-compare:disabled { opacity: 0.4; cursor: not-allowed; }

.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 20px;
  background: #fff;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  margin: 12px 0;
}
.empty-icon { font-size: 48px; }
.empty-text { font-size: 13px; color: #64748b; }
.quick-breeds { width: 100%; max-width: 720px; }
.quick-breeds-label { font-size: 11px; color: #94a3b8; text-align: left; margin-bottom: 6px; }
.quick-breeds-row { display: flex; flex-wrap: wrap; gap: 6px; }
.quick-breed-chip {
  font-size: 12px;
  padding: 4px 10px;
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.quick-breed-chip:hover { background: #dbeafe; }
.quick-breed-chip small { color: #64748b; margin-left: 4px; }

.compare-error {
  display: flex;
  gap: 10px;
  align-items: center;
  background: #fef2f2;
  border: 1px solid #fca5a5;
  color: #991b1b;
  padding: 10px 14px;
  border-radius: 6px;
  margin: 12px 0;
}
.error-icon { font-size: 18px; }
.btn-retry {
  margin-left: auto;
  padding: 4px 12px;
  background: #dc2626;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

/* summary-bar：单行流式布局（pill + dot city） */
.summary-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  margin: 12px 0;
  padding: 8px 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
}
.sum-pill {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 2px 8px;
  background: #f1f5f9;
  border-radius: 10px;
  font-size: 11px;
  color: #475569;
}
.sum-pill strong {
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.sum-emoji { font-size: 12px; }
.sum-sep {
  color: #cbd5e1;
  user-select: none;
}
.sum-city {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  font-size: 12px;
}
.sum-city .city-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 3px;
  transform: translateY(1px);
}
.sum-city strong {
  color: #1e293b;
  font-weight: 600;
}
.sum-city .sum-price {
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  margin-left: 2px;
}
.sum-city .sum-price small {
  font-size: 10px;
  font-weight: 400;
  color: #64748b;
  margin-left: 2px;
}
.sum-city .sum-meta {
  font-size: 10px;
  color: #94a3b8;
  margin-left: 4px;
}
.sum-city .sum-meta em {
  font-style: normal;
  color: #ea580c;
  margin-left: 2px;
}
.sum-city-empty { opacity: 0.55; }

.spec-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 8px 0 12px;
  padding: 8px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}
.spec-label {
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  margin-right: 4px;
}
.spec-chip {
  font-size: 11px;
  padding: 3px 9px;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid transparent;
  border-radius: 3px;
  cursor: pointer;
  transition: all 0.15s;
}
.spec-chip small { color: #94a3b8; }
.spec-chip:hover { border-color: #cbd5e1; }
.spec-chip.active {
  background: #ecfdf5;
  color: #047857;
  border-color: #6ee7b7;
  font-weight: 500;
}
.spec-chip.active small { color: #047857; }
.spec-bar-hint {
  margin-left: auto;
  font-size: 10px;
  color: #94a3b8;
}

.compare-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 12px 8px;
  margin: 8px 0 16px;
  min-height: 320px;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.compare-chart { width: 100%; min-height: 320px; }  /* 单图模式占位（不再使用；高度由 layoutStyle 控制） */

/* small-multiples 网格容器：每格一个独立 echarts 实例 */
.compare-charts-grid {
  display: grid;
  gap: 16px;
}
.compare-chart-cell {
  min-width: 0;
  width: 100%;
  height: 100%;
  min-height: 160px;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  /* 明确边界：浅边 + 圆角 + 阴影 */
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.compare-chart-cell:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}
.cell-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 12px;
  background: #fafbfc;
  border-bottom: 1px solid #f1f5f9;
  border-radius: 7px 7px 0 0;
}
.cell-seq {
  color: #94a3b8;
  font-family: monospace;
  font-size: 10px;
  flex-shrink: 0;
}
.cell-title {
  color: #0f172a;
  font-weight: 600;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cell-align {
  font-family: monospace;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}
.cell-align.align-attr       { background: #dbeafe; color: #1d4ed8; }
.cell-align.align-spec_norm  { background: #fef3c7; color: #a16207; }
.cell-align.align-fallback   { background: #f1f5f9; color: #64748b; }
.cell-chart {
  flex: 1;
  min-height: 0;
  position: relative;
}
.compare-empty {
  padding: 24px 16px;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
}
.compare-empty .empty-title { font-size: 13px; font-weight: 600; color: #475569; }
.compare-empty .empty-detail { font-size: 12px; color: #94a3b8; margin-top: 6px; line-height: 1.5; }

/* 价差走势区（P0-#3） */
.export-bar {
  display: inline-flex;
  gap: 6px;
}
.export-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 11px;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s;
}
.export-btn:hover {
  border-color: #ea580c;
  color: #c2410c;
  background: #fff7ed;
}
.spread-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  margin: 0 0 16px;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.spread-chart { width: 100%; height: 320px; }
.spread-quick {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
}
.spread-quick-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 4px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  font-size: 11px;
  color: #475569;
}
.spread-quick-pill strong { color: #0f172a; }
.sp-emoji { font-size: 12px; }
.sp-val { color: #1e293b; font-weight: 600; margin-left: 2px; font-variant-numeric: tabular-nums; }
.sp-pct {
  margin-left: 4px;
  padding: 1px 6px;
  border-radius: 3px;
  font-style: normal;
  font-weight: 600;
  background: #f1f5f9;
  color: #16a34a;
}
.spread-quick-pill.spread-mid .sp-pct { background: #fef3c7; color: #d97706; }
.spread-quick-pill.spread-severe .sp-pct { background: #fee2e2; color: #dc2626; }

/* 跨城单位不一致警告 */
.unit-conflict-warning {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  background: #fef3c7;
  border: 1px solid #fcd34d;
  color: #92400e;
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 12px;
  margin: 8px 0 4px;
  line-height: 1.6;
}
.unit-conflict-warning .warn-icon {
  font-size: 16px;
  line-height: 1.2;
}
.unit-conflict-warning strong {
  font-weight: 600;
  color: #b45309;
}
.unit-conflict-warning em {
  font-style: normal;
  font-family: var(--font-mono-num, monospace);
  padding: 1px 6px;
  background: #fff7ed;
  border-radius: 3px;
  color: #9a3412;
}
.unit-conflict-warning .warn-tip {
  display: block;
  margin-top: 4px;
  color: #78350f;
  font-size: 11px;
}

.period-table-scroll, .city-detail { overflow-x: auto; }
.period-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin: 12px 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}
.period-table th, .period-table td {
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid #f1f5f9;
}
.period-table th {
  background: #f8fafc;
  font-weight: 600;
  color: #475569;
  font-size: 11px;
}
.period-table th.th-spread { background: #eff6ff; }
.th-city { font-weight: 600 !important; }
.td-period { color: #0f172a; font-weight: 500; }
.td-price { text-align: right; vertical-align: middle; }
.price-val {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.price-meta { font-size: 10px; color: #94a3b8; }
.td-price.missing { background: #fafafa; }
.td-spread { vertical-align: middle; }
.spread-val {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: #0f172a;
}
.spread-pct {
  display: inline-block;
  margin-left: 6px;
  padding: 2px 6px;
  font-size: 10px;
  font-weight: 600;
  border-radius: 3px;
}
.spread-pct.spread-low { background: #ecfdf5; color: #047857; }
.spread-pct.spread-mid { background: #fef3c7; color: #a16207; }
.spread-pct.spread-huge { background: #fef2f2; color: #b91c1c; }
.no-data { color: #cbd5e1; }

.city-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 12px;
  margin: 12px 0;
}
.city-detail {
  --accent: #64748b;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
}
.city-detail-head {
  padding: 8px 14px;
  color: #fff;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-radius: 6px 6px 0 0;
}
.city-name { font-size: 13px; font-weight: 600; }
.city-meta { font-size: 11px; opacity: 0.9; }
.city-meta em {
  font-style: normal;
  background: rgba(255, 255, 255, 0.25);
  padding: 0 4px;
  border-radius: 2px;
  margin-right: 4px;
  font-size: 10px;
}
.city-meta .missing-tag { margin-left: 6px; color: #fef08a; }
.city-empty { padding: 30px; text-align: center; color: #94a3b8; font-size: 12px; }
.city-spec-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.city-spec-table th {
  background: #f8fafc;
  padding: 6px;
  font-weight: 500;
  color: #64748b;
  text-align: right;
  border-bottom: 1px solid #e2e8f0;
}
.city-spec-table th:first-child { text-align: left; }
.city-spec-table td {
  padding: 5px 6px;
  border-bottom: 1px solid #f1f5f9;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.td-spec-label {
  text-align: left !important;
  color: #0f172a;
  font-weight: 500;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.align-tag {
  display: inline-block;
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 2px;
  font-size: 9px;
  font-weight: 500;
}
.align-tag.align-attr { background: #dbeafe; color: #1d4ed8; }
.align-tag.align-spec_norm { background: #fef3c7; color: #a16207; }
.align-tag.align-fallback { background: #f1f5f9; color: #64748b; }
.sp-val { font-weight: 600; color: #0f172a; }
.sp-meta { font-size: 9px; color: #94a3b8; }

/* ── B 方案：品种推荐区 ─────────────────────────────────────────── */
.browse-tree-btn {
  float: right;
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #475569;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  font-weight: normal;
  transition: all 0.15s;
}
.browse-tree-btn:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
  color: #0f172a;
}
.recommend-hint {
  margin-top: 6px;
  font-size: 11px;
  color: #94a3b8;
  display: flex;
  align-items: center;
  gap: 6px;
}
.recommend-hint .loading-spinner {
  width: 12px; height: 12px;
  border: 2px solid #cbd5e1;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.recommend-box {
  margin-top: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
  padding: 8px 10px;
}
.classify-card {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #334155;
}
.classify-icon { font-size: 13px; }
.classify-l3 { flex: 1; min-width: 0; }
.classify-l3 strong { color: #0f172a; font-family: monospace; }
.classify-l3 em { font-style: normal; color: #1d4ed8; font-weight: 500; }
.classify-gb {
  font-size: 10px;
  padding: 1px 6px;
  background: #dbeafe;
  color: #1e40af;
  border-radius: 3px;
  font-family: monospace;
}
.classify-siblings {
  font-size: 11px;
  color: #64748b;
}
.classify-siblings strong { color: #7c3aed; }

.recommend-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.recommend-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 3px 8px;
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 3px;
  cursor: pointer;
  color: #334155;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: all 0.15s;
}
.recommend-chip:hover {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #1d4ed8;
}
.chip-city {
  font-size: 9px;
  padding: 0 4px;
  background: #dcfce7;
  color: #15803d;
  border-radius: 2px;
  font-weight: 500;
}
.recommend-more {
  font-size: 11px;
  color: #64748b;
  padding: 3px 6px;
  cursor: pointer;
}
.recommend-more:hover { color: #1d4ed8; }

.recommend-note {
  margin-top: 6px;
  padding: 4px 8px;
  font-size: 10px;
  color: #92400e;
  background: #fef3c7;
  border-radius: 3px;
  line-height: 1.5;
}

/* NORM 跨城归一品种区（与 recommend 并列展示） */
.norm-compare-box {
  margin-top: 6px;
  padding: 6px 10px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 4px;
}
.norm-compare-title {
  display: block;
  font-size: 10px;
  color: #0369a1;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}
.norm-compare-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.norm-compare-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  background: #fff;
  border: 1px solid #7dd3fc;
  border-radius: 3px;
  font-size: 11px;
  color: #0c4a6e;
  cursor: pointer;
  transition: all 0.15s;
  max-width: 100%;
  overflow: hidden;
}
.norm-compare-item:hover {
  background: #bae6fd;
  color: #082f49;
}
.norm-compare-breed {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.norm-compare-meta {
  font-size: 10px;
  color: #0369a1;
  background: #e0f2fe;
  padding: 0 5px;
  border-radius: 2px;
  white-space: nowrap;
}

/* ── C 方案：分类树抽屉 ───────────────────────────────────────── */
.tree-drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.4);
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
}
.tree-drawer {
  width: 480px;
  max-width: 90vw;
  height: 100%;
  background: #fff;
  box-shadow: -4px 0 20px rgba(0,0,0,0.15);
  display: flex;
  flex-direction: column;
  animation: slideIn 0.2s ease-out;
}
@keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
.tree-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}
.tree-drawer-head h3 { margin: 0; font-size: 14px; color: #0f172a; }
.tree-close {
  border: none;
  background: transparent;
  font-size: 18px;
  color: #94a3b8;
  cursor: pointer;
  padding: 0 6px;
}
.tree-close:hover { color: #0f172a; }

.tree-loading {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 13px;
}
.tree-body { flex: 1; overflow-y: auto; padding: 8px 0; }
.tree-stats {
  font-size: 11px;
  color: #64748b;
  padding: 4px 16px 10px;
  border-bottom: 1px solid #f1f5f9;
}
.tree-stats strong { color: #7c3aed; }

.tree-list { padding: 0 8px; }
.tree-node { font-size: 12px; }
.tree-node-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  user-select: none;
}
.tree-node-row:hover { background: #f1f5f9; }
.tree-toggle {
  width: 12px;
  font-size: 9px;
  color: #94a3b8;
  font-family: monospace;
}
.tree-code {
  font-family: monospace;
  font-size: 10px;
  color: #64748b;
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 2px;
  min-width: 40px;
  text-align: center;
}
.tree-name {
  flex: 1;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-meta {
  font-size: 10px;
  color: #94a3b8;
}
.tree-children { padding-left: 16px; border-left: 1px dashed #e2e8f0; margin-left: 12px; }
.tree-l2 .tree-node-row { padding: 3px 6px; font-size: 12px; }
.tree-l2 .tree-code { background: #ecfdf5; color: #047857; }
.tree-l3 .tree-node-row { padding: 2px 6px; font-size: 11px; }
.tree-l3 .tree-code { background: #fef3c7; color: #92400e; }
.tree-l3-breeds { padding: 4px 6px 6px 24px; }
.tree-l3-btn {
  font-size: 11px;
  padding: 3px 8px;
  border: 1px dashed #cbd5e1;
  background: #fff;
  color: #475569;
  border-radius: 3px;
  cursor: pointer;
}
.tree-l3-btn:hover { background: #eff6ff; border-color: #3b82f6; color: #1d4ed8; }
.tree-l3-empty { font-size: 11px; color: #94a3b8; }
</style>
