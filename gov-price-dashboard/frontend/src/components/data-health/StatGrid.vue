<!--
  StatGrid.vue (2026-07-28 新增 · Step 3 / 3 架构重构)
  从 DataHealthView 顶部抽出的 4 张统计卡 — 总数据量 / 抓取任务 / 平均新鲜度 / 异常告警
  DataHealthView 从 853 行 → 大幅瘦身(目标 <500 行)
  Props 直接传数,父组件无需暴露内部 computed
-->
<template>
  <div class="health-cards">
    <el-card shadow="never" class="health-stat-card">
      <el-statistic :value="totalDocs" title="总数据量" suffix=" 条">
        <template #prefix><el-icon><Document /></el-icon></template>
      </el-statistic>
    </el-card>

    <el-card shadow="never" class="health-stat-card">
      <el-statistic :value="skillTotal" title="抓取任务" suffix=" 个">
        <template #prefix><el-icon><Files /></el-icon></template>
      </el-statistic>
    </el-card>

    <el-card shadow="never" class="health-stat-card">
      <el-statistic :value="avgFreshness" title="平均新鲜度" suffix=" 天前">
        <template #prefix><el-icon><Timer /></el-icon></template>
      </el-statistic>
    </el-card>

    <el-card
      shadow="never"
      class="health-stat-card"
      :class="{ 'is-danger': anomalyTotal > 0 }"
    >
      <el-statistic
        :value="anomalyTotal"
        :title="anomalyTotal > 0 ? '异常告警' : '全部正常'"
        :suffix="anomalyTotal > 0 ? ' 个 skill' : ' 个'"
      >
        <template #prefix><el-icon><Warning /></el-icon></template>
      </el-statistic>
    </el-card>
  </div>
</template>

<script setup>
/**
 * DataHealthView 顶部 4 张统计卡组件
 *
 * Props:
 *   totalDocs      - 总文档数(data.total_docs)
 *   skillTotal     - 抓取任务总数(skillStats.total)
 *   avgFreshness   - 平均新鲜度天数(skillStats.avgFreshness,保留 1 位小数)
 *   anomalyTotal   - 异常告警数(anomalyStats.total)
 *
 * 设计:
 * - 父组件把数据传进来即可,子组件不做任何计算 — 保持单一职责
 * - el-card :class="{ 'is-danger': anomalyTotal > 0 }" 由 CSS 控制红色边框
 */
import { Document, Files, Timer, Warning } from '@element-plus/icons-vue'

defineProps({
  totalDocs: { type: Number, default: 0 },
  skillTotal: { type: Number, default: 0 },
  avgFreshness: { type: Number, default: 0 },
  anomalyTotal: { type: Number, default: 0 },
})
</script>

<style scoped>
.health-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  flex-wrap: wrap;
}
.health-stat-card :deep(.el-card__body) {
  padding: 14px 16px;
}
.health-stat-card :deep(.el-statistic__head) {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
  margin-bottom: 4px;
}
.health-stat-card :deep(.el-statistic__content) {
  font-size: 22px;
  font-weight: 700;
  color: #111827;
  line-height: 1.2;
  font-feature-settings: "tnum";
}
.health-stat-card :deep(.el-statistic__prefix) {
  margin-right: 6px;
  color: #94a3b8;
  font-size: 14px;
}
.health-stat-card.is-danger :deep(.el-statistic__content) {
  color: #dc2626;
}
.health-stat-card.is-danger :deep(.el-statistic__prefix) {
  color: #dc2626;
}

/* 小屏 2 列;超小屏 1 列 */
@media (max-width: 900px) {
  .health-cards { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 520px) {
  .health-cards { grid-template-columns: 1fr; }
}
</style>