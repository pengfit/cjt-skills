<template>
  <div class="trend-page">
    <!-- 顶部信息 + tab 切换 -->
    <PageHeader
      variant="flat"
      title="价格走势"
      :subtitle="trendMode === 'category'
        ? `基于 normalized_breed 的品类级视角 · 规格热力图 + 价格带 + 同 L3 横向推荐`
        : `跨城同品种时序对比 · 按 attr-based spec_key 拼接 · 同单位约束，周期以日历对齐`"
    >
      <template #icon>📈</template>
      <template #right>
        <div class="trend-mode-tabs">
          <button
            class="mode-tab"
            :class="{ active: trendMode === 'category' }"
            @click="trendMode = 'category'"
          >品类聚合</button>
          <button
            class="mode-tab"
            :class="{ active: trendMode === 'compare' }"
            @click="trendMode = 'compare'"
          >跨城市对比</button>
        </div>
      </template>
    </PageHeader>

    <!-- 品类聚合面板（默认） -->
    <CategoryTrendView v-if="trendMode === 'category'" />

    <!-- 跨城对比面板 -->
    <PriceTrendComparePanel v-if="trendMode === 'compare'" />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import PriceTrendComparePanel from './PriceTrendComparePanel.vue'
import CategoryTrendView from './CategoryTrendView.vue'
import PageHeader from './PageHeader.vue'

// 顶部 tab 状态：'category' | 'compare'（2026-07-09 移除 'single'，/api/stats/price-trend 不再使用）
const trendMode = ref('category')
</script>

<style scoped>
.trend-page {
  padding: 16px 20px 80px;
  min-height: 100vh;
  color: #1e293b;
}

/* 顶部 tab：品类聚合 / 跨城市对比 */
.trend-mode-tabs {
  display: inline-flex;
  background: #f1f5f9;
  border-radius: 6px;
  padding: 3px;
  gap: 2px;
}
.mode-tab {
  border: none;
  background: transparent;
  padding: 6px 14px;
  border-radius: 4px;
  font-size: 12px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
}
.mode-tab:hover { color: #0f172a; }
.mode-tab.active {
  background: #fff;
  color: #1d4ed8;
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(15,23,42,0.08);
}
</style>
