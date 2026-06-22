<template>
  <div class="cleandim-page">

    <!-- Page header -->
    <PageHeader
      variant="flat"
      title="分类清洗"
      subtitle="按一级分类 × 城市覆盖 × 解析率，横向看全国 9 城 DWD 数据分类清洗状况"
      :stats="cleanCategory.items.length ? [
        { label: '清洗文档数', value: cleanCategory.total.toLocaleString() },
        { label: '覆盖分类数', value: cleanCategory.items.length },
      ] : []"
    ><template #icon>🧪</template></PageHeader>

    <!-- 分类清洗 -->
    <div class="chart-panel" v-if="cleanCategory.items.length">
      <SectionHeader
        title="分类清洗"
        dot-color="blue"
        :subtitle="`一级分类 × 城市覆盖 · ${cleanCategory.total.toLocaleString()} 条 / ${cleanCategory.items.length} 分类`"
        style="margin-bottom:12px"
      />
      <div class="clean-table">
        <div class="clean-table-header">
          <span class="clean-col-key">分类</span>
          <span class="clean-col-count">文档数</span>
          <span class="clean-col-cities">城市覆盖</span>
          <span class="clean-col-parse">规格解析率</span>
        </div>
        <div
          v-for="c in cleanCategory.items"
          :key="c.key"
          class="clean-table-row"
        >
          <span class="clean-col-key" :title="c.key">{{ c.key }}</span>
          <span class="clean-col-count">{{ c.doc_count.toLocaleString() }}</span>
          <span class="clean-col-cities">
            <span
              v-for="city in allCityKeys"
              :key="city"
              class="clean-city-dot"
              :class="{ active: c.cities.includes(city) }"
              :title="`${cityMap[city] || city}: ${c.cities.includes(city) ? '有数据' : '无数据'}`"
            ></span>
            <span class="clean-city-count">{{ c.city_count }}/{{ c.cities_total || 8 }}</span>
          </span>
          <span class="clean-col-parse">
            <span class="clean-parse-bar">
              <span class="clean-parse-fill" :style="{ width: (c.parse_rate * 100) + '%' }"></span>
            </span>
            <span class="clean-parse-num">{{ (c.parse_rate * 100).toFixed(1) }}%</span>
          </span>
        </div>
      </div>
    </div>

    <!-- 加载/空/错状态 -->
    <div v-if="loading" class="cleandim-loading">
      <SkeletonCard :lines="4" :hide-footer="true" />
    </div>
    <EmptyState
      v-else-if="!cleanCategory.items.length"
      icon="🧪" title="暂无数据" message="该页面需要先运行过 ETL 清洗任务"
    />
    <ErrorState v-if="error" :title="'加载失败'" :message="error" compact :on-retry="loadData" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import SkeletonCard from './SkeletonCard.vue'
import EmptyState from './EmptyState.vue'
import ErrorState from './ErrorState.vue'
import SectionHeader from './SectionHeader.vue'
import PageHeader from './PageHeader.vue'

const API = import.meta.env.VITE_API_URL || '/api'

const loading = ref(false)
const error = ref('')

const cleanCategory = ref({ items: [], total: 0 })

// 9 城 city key 列表（用于城市覆盖点）
const cityMap = {
  xian: '西安', sichuan: '四川', chongqing: '重庆', jinan: '济南',
  rizhao: '日照', henan: '河南', heze: '菏泽', qingdao: '青岛',
  weihai: '威海',
}
const allCityKeys = Object.keys(cityMap)

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const catRes = await axios.get(`${API}/stats/clean-summary?dim=category&top_n=30`)
    cleanCategory.value = catRes.data || { items: [], total: 0 }
  } catch (e) {
    error.value = '加载失败：' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.cleandim-page {
  padding: 16px 20px 80px;
  min-height: 100vh;
  color: #1e293b;
}

/* === Page header（已迁移至 PageHeader flat 变体） === */

/* panel-header / panel-title / panel-dot / panel-meta 已迁移至 SectionHeader.vue */

/* === 清洗维度表（分类清洗 / 规格清洗 共用） === */
.clean-table { display: flex; flex-direction: column; gap: 0; }
.clean-table-header,
.clean-table-row {
  display: grid;
  grid-template-columns: minmax(120px, 1.5fr) 80px minmax(180px, 2fr) minmax(140px, 1.2fr);
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  font-size: 12px;
}
.clean-table-header {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 6px;
}
.clean-table-row {
  border-bottom: 1px solid rgba(15, 23, 42, 0.04);
  transition: background 0.15s;
}
.clean-table-row:hover { background: rgba(37, 99, 235, 0.03); }
.clean-table-row:last-child { border-bottom: none; }
.clean-col-key {
  color: #0f172a;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.clean-col-count {
  color: #475569;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  text-align: right;
}
.clean-col-cities { display: flex; align-items: center; gap: 3px; }
.clean-city-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e2e8f0;
  transition: background 0.15s;
}
.clean-city-dot.active { background: #2563eb; }
.clean-city-count {
  font-size: 11px;
  color: #94a3b8;
  margin-left: 6px;
  font-variant-numeric: tabular-nums;
}
.clean-col-parse { display: flex; align-items: center; gap: 8px; }
.clean-parse-bar {
  flex: 1;
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
}
.clean-parse-fill {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #2563eb 0%, #16a34a 100%);
  border-radius: 3px;
  transition: width 0.3s ease;
}
.clean-parse-num {
  font-size: 11px;
  color: #475569;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  min-width: 40px;
  text-align: right;
}

/* 加载/空/错 */
.cleandim-loading {
  display: flex;
  justify-content: center;
  padding: 40px 0;
}
</style>
