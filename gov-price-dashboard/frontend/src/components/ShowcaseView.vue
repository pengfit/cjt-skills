<!--
  ShowcaseView.vue (2026-07-20 OPC 主题重构 - One Person Company)

  /index 首页 - 5 个 section · OPC 一人公司叙事
  路径:/index (公开访问,不鉴权)

  2026-07-20 改造(主题级重构):
    1. Nav/Hero/Footer 品牌 → "One Person Company"
    2. Workspace 对比 → 传统公司 vs OPC 一人公司
    3. Case 视角 → 1 人公司跑通 17 城数据业务
    4. 新增 ShowcaseBusiness · 6 大能力全景 + 成本对比
-->
<template>
  <div class="showcase">
    <ShowcaseNav />
    <main class="showcase-main">
      <ShowcaseHero />
      <ShowcaseWorkspace />
      <ShowcaseBusiness />
      <ShowcaseCase />
    </main>
    <ShowcaseFooter />
  </div>
</template>

<script setup>
import { provide } from 'vue'
import ShowcaseNav from './showcase/ShowcaseNav.vue'
import ShowcaseHero from './showcase/ShowcaseHero.vue'
import ShowcaseWorkspace from './showcase/ShowcaseWorkspace.vue'
import ShowcaseBusiness from './showcase/ShowcaseBusiness.vue'
import ShowcaseCase from './showcase/ShowcaseCase.vue'
import ShowcaseFooter from './showcase/ShowcaseFooter.vue'

// 注意:ShowcaseInsight 已并入 ShowcaseCase 顶部(从顶层独立 section 移入案例内容)

// 静态数据(写死) - 数据时间:2026-07-19,来源 /api/showcase/stats 最后一次快照
// /index 不再调用 API(已是静态页面),stats 保留用于潜在引用
const stats = {
  cities_count: 20,
  provinces_count: 15,
  dws_total: 788525,
  dwd_total: 869441,
  ods_total: 907316,
  norm_total: 788525,
  total_records: 788525,
  breeds_count: 9931,
  categories_count: 9,
  storage_mb: 573.1,
  latest_update: '2026-07-31',
  provinces_grouped: [
    { name: '内蒙古', cities: [{ key: 'huhehaote', label: '呼和浩特', latest: '2026-02-28', count: 1803 }] },
    { name: '吉林', cities: [{ key: 'jilin', label: '吉林', latest: '2026-07-31', count: 5124 }] },
    { name: '四川', cities: [{ key: 'sichuan', label: '四川', latest: '2026-05-31', count: 421345 }] },
    { name: '宁夏', cities: [{ key: 'ningxia', label: '宁夏', latest: '2026-06-30', count: 7747 }] },
    { name: '山东', cities: [
      { key: 'weihai', label: '威海', latest: '2026-03-31', count: 818 },
      { key: 'rizhao', label: '日照', latest: '2026-05-31', count: 4973 },
      { key: 'jinan', label: '济南', latest: '2026-05-31', count: 24487 },
      { key: 'heze', label: '菏泽', latest: '2026-01-31', count: 868 },
      { key: 'qingdao', label: '青岛', latest: '2026-06-30', count: 1307 },
    ] },
    { name: '山西', cities: [{ key: 'shanxi', label: '山西', latest: '2026-04-30', count: 11436 }] },
    { name: '新疆', cities: [{ key: 'xinjiang', label: '新疆', latest: '2026-05-31', count: 100990 }] },
    { name: '江西', cities: [{ key: 'jiangxi', label: '江西', latest: '2026-07-31', count: 45579 }] },
    { name: '河南', cities: [{ key: 'henan', label: '河南', latest: '2026-04-30', count: 8234 }] },
    { name: '海南', cities: [{ key: 'hainan', label: '海南', latest: '2026-04-30', count: 12278 }] },
    { name: '湖南', cities: [{ key: 'hunan', label: '湖南', latest: '2026-04-30', count: 2282 }] },
    { name: '贵州', cities: [{ key: 'guizhou', label: '贵州', latest: '2026-06-30', count: 17072 }] },
    { name: '重庆', cities: [{ key: 'chongqing', label: '重庆', latest: '2026-05-31', count: 8578 }] },
    { name: '陕西', cities: [
      { key: 'xian', label: '西安', latest: '2026-06-30', count: 69654 },
      { key: 'shaanxi', label: '陕西', latest: '2026-06-30', count: 33475 },
    ] },
    { name: '青海', cities: [{ key: 'qinghai', label: '青海', latest: '2026-06-30', count: 10475 }] },
  ],
}

// 给 Hero(用 inject)提供数据
provide('stats', stats)
</script>

<style scoped>
.showcase {
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  display: flex;
  flex-direction: column;
}

.showcase-main {
  flex: 1;
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 32px;
}
</style>