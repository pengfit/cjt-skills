<template>
  <div class="health-page" :class="{ 'show-card-detail': showCardDetail }">

    <!-- 顶部标题栏 -->
    <div class="health-header">
      <div class="header-inner">
        <div class="header-left">
          <div class="header-icon">📊</div>
          <div class="header-titles">
            <div class="health-title">数据监控大屏</div>
            <div class="health-subtitle">实时追踪各省份数据同步状态</div>
          </div>
        </div>
        <div class="header-right">
          <div class="header-time">{{ currentTime }}</div>
          <button class="btn-refresh" @click="loadData()" :class="{ spinning: loading }">
            <span class="refresh-icon">🔄</span> 刷新数据
          </button>
        </div>
      </div>
    </div>

    <!-- 四个汇总指标卡 -->
    <div class="health-cards">
      <div class="stat-card stat-card-primary">
        <div class="stat-card-inner">
          <div class="stat-icon">📄</div>
          <div class="stat-content">
            <div class="stat-label">总数据量</div>
            <div class="stat-value"><span class="stat-num">{{ data.total_docs.toLocaleString() }}</span><span class="stat-unit">条</span></div>
          </div>
          <div class="stat-glow"></div>
        </div>
      </div>
      <div class="stat-card stat-card-cyan">
        <div class="stat-card-inner">
          <div class="stat-icon">🏛️</div>
          <div class="stat-content">
            <div class="stat-label">省份数量</div>
            <div class="stat-value"><span class="stat-num">{{ data.province_count }}</span><span class="stat-unit">个</span></div>
          </div>
          <div class="stat-glow"></div>
        </div>
      </div>
      <div class="stat-card stat-card-warning" :class="{ 'stat-alert': data.stale_provinces > 0 }">
        <div class="stat-card-inner">
          <div class="stat-icon">⚠️</div>
          <div class="stat-content">
            <div class="stat-label">数据滞后省份</div>
            <div class="stat-value"><span class="stat-num">{{ data.stale_provinces }}</span><span class="stat-unit">个</span></div>
          </div>
          <div class="stat-glow"></div>
        </div>
      </div>
    </div>

    <!-- 图表区域 -->
    <div class="chart-panel">
      <div class="panel-header">
        <div class="panel-title-row">
          <span class="panel-dot panel-dot-blue"></span>
          <span class="panel-title">近30日数据量趋势</span>
        </div>
        <div class="chart-legend">
          <span class="legend-item"><span class="legend-dot"></span>日增量</span>
        </div>
      </div>
      <div id="dailyTrendChart" class="chart-area"></div>
    </div>

    <!-- 省份同步卡片网格 -->
    <div class="sync-grid-tools">
      <span class="sync-grid-hint">默认只显示概览，点击「展开详情」查看区县进度与环状圈</span>
      <button class="sync-grid-toggle" @click="showCardDetail = !showCardDetail">
        {{ showCardDetail ? '▴ 收起详情' : '▾ 展开详情' }}
      </button>
    </div>
    <div class="sync-grid">

      <!-- 西安 -->
      <div class="sync-card" :class="{ 'sync-card-running': syncData.status === 'running' }">
        <div class="sync-card-bar sync-bar-xa"></div>
        <div class="sync-card-content">
          <div class="sync-card-header">
            <div class="sync-card-title-row">
              <span class="sync-province-tag tag-xa">西安</span>
              <span class="sync-card-title">工程造价材料信息</span>
            </div>
            <div class="sync-badges">
              <span v-if="syncData.spot_check_ok === true" class="badge badge-green">✓ 抽检通过</span>
              <span v-else-if="syncData.spot_check_ok === false" class="badge badge-red">✗ 抽检异常</span>
              <span v-if="syncData.has_incremental === true" class="badge badge-green">有增量</span>
              <span v-else-if="syncData.has_incremental === false && syncData.last_sync_date" class="badge badge-blue">{{ syncData.last_sync_date }}</span>
              <span v-else-if="syncData.has_incremental === false" class="badge badge-blue">已同步</span>
            </div>
          </div>
          <div class="sync-card-meta">{{ formatDur(syncData.duration_sec) }} · {{ syncData.last_updated || '—' }}</div>

          <div class="sync-card-body">
            <div class="sync-info-col">
              <svg class="ring" viewBox="0 0 100 100">
                <circle class="ring-bg" cx="50" cy="50" r="40" />
                <circle class="ring-fill ring-xa" cx="50" cy="50" r="40"
                  :stroke-dasharray="251.327"
                  :stroke-dashoffset="251.327 * (1 - Math.min((syncData.completed_counties || 0) / 6, 1))" />
                <text class="ring-pct" x="50" y="46" text-anchor="middle" font-size="18" font-weight="700">{{ (syncData.completed_counties || 0) + '/' + (syncData.total_counties || 37) }}</text>
                <text class="ring-sub" x="50" y="64" text-anchor="middle" font-size="10">{{ syncData.status === 'completed' ? '全部完成' : '进行中' }}</text>
              </svg>
              <div class="sync-status-row">
                <span v-if="syncData.status === 'running'" class="badge badge-blue">● 同步中</span>
                <span v-else-if="syncData.status === 'completed'" class="badge badge-green">✓ 已完成</span>
                <span v-else-if="syncData.status === 'interrupted'" class="badge badge-yellow">⚠ 已中断</span>
                <span v-else-if="syncData.status === 'error'" class="badge badge-red">✗ 出错</span>
                <span v-else class="badge badge-gray">— 无记录</span>
              </div>
              <div class="sync-doc-count">{{ (syncData.total_docs || 0).toLocaleString() }} 条文档</div>
            </div>

            <div class="sync-list-col">
              <div class="list-header"><span>区县</span><span>状态</span><span>文档数</span><span>期数</span></div>
              <div class="list-scroll">
                <div class="list-row" v-for="c in pagedCounties" :key="c.county"
                  :class="{ 'row-active': syncData.current_county === c.county && syncData.status === 'running' }">
                  <span class="list-name">{{ c.county }}</span>
                  <span>
                    <span v-if="syncData.current_county === c.county && syncData.status === 'running'" class="badge badge-blue">●</span>
                    <span v-else-if="c.status === 'completed'" class="badge badge-green">✓</span>
                    <span v-else class="badge badge-gray">—</span>
                  </span>
                  <span class="list-num">{{ (c.doc_count || 0).toLocaleString() }}</span>
                  <span class="list-date">{{ c.last_updated || '—' }}</span>
                </div>
              </div>
              <div class="list-pagination" v-if="totalCountyPages > 1">
                <button class="pg-btn" @click="countyPage--" :disabled="countyPage <= 1">‹</button>
                <span class="pg-info">{{ countyPage }}/{{ totalCountyPages }}</span>
                <button class="pg-btn" @click="countyPage++" :disabled="countyPage >= totalCountyPages">›</button>
              </div>
              <div class="progress-wrap" v-if="syncData.current_county && syncData.status === 'running'">
                <div class="progress-bar">
                  <div class="progress-fill progress-fill-xa" :style="{ width: getCountyPercent().toFixed(1) + '%' }"></div>
                </div>
                <div class="progress-info">
                  <span>{{ syncData.current_page }}/{{ syncData.total_pages }}页</span>
                  <span class="pct-active">{{ getCountyPercent().toFixed(1) }}%</span>
                  <span>{{ syncData.county_details?.find(c => c.county === syncData.current_county)?.doc_count?.toLocaleString() || 0 }}条</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 四川 -->
      <div class="sync-card" :class="{ 'sync-card-running': sichuanSyncData.status === 'running' }">
        <div class="sync-card-bar sync-bar-sc"></div>
        <div class="sync-card-content">
          <div class="sync-card-header">
            <div class="sync-card-title-row">
              <span class="sync-province-tag tag-sc">四川</span>
              <span class="sync-card-title">工程造价材料信息</span>
            </div>
            <div class="sync-badges">
              <span v-if="sichuanSyncData.has_incremental === true" class="badge badge-green">有新周期</span>
              <span v-else-if="sichuanSyncData.has_incremental === false && sichuanSyncData.es_latest_period" class="badge badge-blue">{{ sichuanSyncData.es_latest_period }}</span>
              <span v-else-if="sichuanSyncData.has_incremental === false" class="badge badge-blue">已同步</span>
            </div>
          </div>
          <div class="sync-card-meta">{{ formatDur(sichuanSyncData.duration_sec) }} · {{ sichuanSyncData.last_updated || '—' }}</div>

          <div class="sync-card-body">
            <div class="sync-info-col">
              <svg class="ring" viewBox="0 0 100 100">
                <circle class="ring-bg" cx="50" cy="50" r="40" />
                <circle class="ring-fill ring-sc" cx="50" cy="50" r="40"
                  :stroke-dasharray="251.327"
                  :stroke-dashoffset="251.327 * (1 - sichuanRing.pct / 100)" />
                <text class="ring-pct" x="50" y="46" text-anchor="middle" font-size="16" font-weight="700">{{ sichuanRing.done }}/{{ sichuanRing.total }}</text>
                <text class="ring-sub" x="50" y="64" text-anchor="middle" font-size="10">{{ sichuanRing.pct >= 100 ? '全部完成' : '进行中' }}</text>
              </svg>
              <div class="sync-status-row">
                <span v-if="sichuanSyncData.status === 'running'" class="badge badge-blue">● 同步中</span>
                <span v-else-if="sichuanSyncData.status === 'completed'" class="badge badge-green">✓ 已完成</span>
                <span v-else-if="sichuanSyncData.status === 'interrupted'" class="badge badge-yellow">⚠ 已中断</span>
                <span v-else-if="sichuanSyncData.status === 'error'" class="badge badge-red">✗ 出错</span>
                <span v-else class="badge badge-gray">— 无记录</span>
              </div>
              <div class="sync-doc-count">{{ (sichuanSyncData.total_docs || 0).toLocaleString() }} 条文档</div>
            </div>

            <div class="sync-list-col">
              <div class="list-header"><span>地区</span><span>状态</span><span>文档数</span><span>最新更新</span></div>
              <div class="list-scroll">
                <div class="list-row" v-for="d in pagedSichuan" :key="d.area">
                  <span class="list-name">{{ d.area }}</span>
                  <span>
                    <span v-if="d.status === 'completed'" class="badge badge-green">✓</span>
                    <span v-else-if="d.status === 'running'" class="badge badge-blue">●</span>
                    <span v-else class="badge badge-gray">—</span>
                  </span>
                  <span class="list-num">{{ (d.docs_written || 0).toLocaleString() }}</span>
                  <span class="list-date">{{ d.last_updated || '—' }}</span>
                </div>
              </div>
              <div class="list-pagination" v-if="totalSichuanPages > 1">
                <button class="pg-btn" @click="sichuanPage--" :disabled="sichuanPage <= 1">‹</button>
                <span class="pg-info">{{ sichuanPage }}/{{ totalSichuanPages }}</span>
                <button class="pg-btn" @click="sichuanPage++" :disabled="sichuanPage >= totalSichuanPages">›</button>
              </div>
              <div class="progress-wrap" v-if="sichuanSyncData.area && sichuanSyncData.status === 'running'">
                <div class="progress-bar">
                  <div class="progress-fill progress-fill-sc" :style="{ width: getSichuanPercent().toFixed(1) + '%' }"></div>
                </div>
                <div class="progress-info">
                  <span>{{ sichuanSyncData.area }}</span>
                  <span>{{ sichuanSyncData.current_page }}/{{ sichuanSyncData.total_pages }}页</span>
                  <span class="pct-active">{{ getSichuanPercent().toFixed(1) }}%</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 日照 -->
      <div class="sync-card" :class="{ 'sync-card-running': rizhaoSyncData.status === 'running' }">
        <div class="sync-card-bar sync-bar-rz"></div>
        <div class="sync-card-content">
          <div class="sync-card-header">
            <div class="sync-card-title-row">
              <span class="sync-province-tag tag-rz">日照</span>
              <span class="sync-card-title">工程造价材料信息</span>
            </div>
            <div class="sync-badges">
              <span v-if="rizhaoSyncData.has_incremental === true" class="badge badge-green">有新数据</span>
              <span v-else-if="rizhaoSyncData.has_incremental === false && rizhaoSyncData.period" class="badge badge-blue">{{ rizhaoSyncData.period }}</span>
              <span v-else-if="rizhaoSyncData.period" class="badge badge-blue">{{ rizhaoSyncData.period }}</span>
            </div>
          </div>
          <div class="sync-card-meta">{{ formatDur(rizhaoSyncData.duration_sec) }} · {{ rizhaoSyncData.last_updated || '—' }}</div>

          <div class="sync-card-body">
            <div class="sync-info-col">
              <svg class="ring" viewBox="0 0 100 100">
                <circle class="ring-bg" cx="50" cy="50" r="40" />
                <circle class="ring-fill ring-rz" cx="50" cy="50" r="40"
                  :stroke-dasharray="251.327"
                  :stroke-dashoffset="251.327 * (1 - rizhaoRing.pct / 100)" />
                <text class="ring-pct" x="50" y="46" text-anchor="middle" font-size="16" font-weight="700">{{ rizhaoRing.done }}/{{ rizhaoRing.total }}</text>
                <text class="ring-sub" x="50" y="64" text-anchor="middle" font-size="10">{{ rizhaoRingAllDone ? '全部完成' : '进行中' }}</text>
              </svg>
              <div class="sync-status-row">
                <span v-if="rizhaoSyncData.status === 'running'" class="badge badge-blue">● 同步中</span>
                <span v-else-if="rizhaoSyncData.status === 'completed'" class="badge badge-green">✓ 已完成</span>
                <span v-else-if="rizhaoSyncData.status === 'interrupted'" class="badge badge-yellow">⚠ 已中断</span>
                <span v-else-if="rizhaoSyncData.status === 'error'" class="badge badge-red">✗ 出错</span>
                <span v-else class="badge badge-gray">— 无记录</span>
              </div>
              <div class="sync-doc-count">{{ (rizhaoSyncData.total_docs || 0).toLocaleString() }} 条文档</div>
            </div>

            <div class="sync-list-col">
              <div class="list-header"><span>类别</span><span>状态</span><span>文档数</span><span>期数</span></div>
              <div class="list-scroll">
                <div class="list-row" v-for="t in pagedRizhao" :key="t.tab_type"
                  :class="{ 'row-active': rizhaoSyncData.current_tab === t.tab_name && rizhaoSyncData.status === 'running' }">
                  <span class="list-name" :title="t.tab_name">{{ t.tab_name || '—' }}</span>
                  <span>
                    <span v-if="t.status === 'completed'" class="badge badge-green">✓</span>
                    <span v-else-if="t.status === 'running'" class="badge badge-blue">●</span>
                    <span v-else-if="t.status === 'interrupted'" class="badge badge-yellow">⚠</span>
                    <span v-else class="badge badge-gray">—</span>
                  </span>
                  <span class="list-num">{{ (t.docs_written || 0).toLocaleString() }}</span>
                  <span class="list-date">{{ t.period || '—' }}</span>
                </div>
              </div>
              <div class="list-pagination" v-if="totalRizhaoPages > 1">
                <button class="pg-btn" @click="rizhaoPage--" :disabled="rizhaoPage <= 1">‹</button>
                <span class="pg-info">{{ rizhaoPage }}/{{ totalRizhaoPages }}</span>
                <button class="pg-btn" @click="rizhaoPage++" :disabled="rizhaoPage >= totalRizhaoPages">›</button>
              </div>
              <div class="progress-wrap" v-if="rizhaoSyncData.current_tab && rizhaoSyncData.status === 'running'">
                <div class="progress-bar">
                  <div class="progress-fill progress-fill-rz" :style="{ width: getRizhaoPercent().toFixed(1) + '%' }"></div>
                </div>
                <div class="progress-info">
                  <span>{{ rizhaoSyncData.current_page }}/{{ rizhaoSyncData.total_pages }}页</span>
                  <span class="pct-active">{{ getRizhaoPercent().toFixed(1) }}%</span>
                  <span>{{ rizhaoSyncData.tab_details?.find(t => t.tab_name === rizhaoSyncData.current_tab)?.docs_written?.toLocaleString() || 0 }}条</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 济南 -->
      <div class="sync-card" :class="{ 'sync-card-running': jinanSyncData.status === 'running' }">
        <div class="sync-card-bar sync-bar-jn"></div>
        <div class="sync-card-content">
          <div class="sync-card-header">
            <div class="sync-card-title-row">
              <span class="sync-province-tag tag-jn">济南</span>
              <span class="sync-card-title">工程造价材料信息</span>
            </div>
            <div class="sync-badges">
              <span v-if="jinanSyncData.has_incremental === true" class="badge badge-green">有新数据</span>
              <span v-else-if="jinanSyncData.has_incremental === false && jinanSyncData.period" class="badge badge-blue">{{ jinanSyncData.period }}</span>
              <span v-else-if="jinanSyncData.period" class="badge badge-blue">{{ jinanSyncData.period }}</span>
            </div>
          </div>
          <div class="sync-card-meta">{{ formatDur(jinanSyncData.duration_sec) }} · {{ jinanSyncData.last_updated || '—' }}</div>

          <div class="sync-card-body">
            <div class="sync-info-col">
              <svg class="ring" viewBox="0 0 100 100">
                <circle class="ring-bg" cx="50" cy="50" r="40" />
                <circle class="ring-fill ring-jn" cx="50" cy="50" r="40"
                  :stroke-dasharray="251.327"
                  :stroke-dashoffset="251.327 * (1 - jinanRing.pct / 100)" />
                <text class="ring-pct" x="50" y="46" text-anchor="middle" font-size="16" font-weight="700">{{ jinanRing.done }}/{{ jinanRing.total }}</text>
                <text class="ring-sub" x="50" y="64" text-anchor="middle" font-size="10">{{ jinanRingAllDone ? '全部完成' : '进行中' }}</text>
              </svg>
              <div class="sync-status-row">
                <span v-if="jinanSyncData.status === 'running'" class="badge badge-blue">● 同步中</span>
                <span v-else-if="jinanSyncData.status === 'completed'" class="badge badge-green">✓ 已完成</span>
                <span v-else-if="jinanSyncData.status === 'interrupted'" class="badge badge-yellow">⚠ 已中断</span>
                <span v-else-if="jinanSyncData.status === 'error'" class="badge badge-red">✗ 出错</span>
                <span v-else class="badge badge-gray">— 无记录</span>
              </div>
              <div class="sync-doc-count">{{ (jinanSyncData.total_docs || 0).toLocaleString() }} 条文档</div>
            </div>

            <div class="sync-list-col">
              <div class="list-header"><span>分类</span><span>状态</span><span>文档数</span><span>最新更新</span></div>
              <div class="list-scroll">
                <div class="list-row" v-for="c in pagedJinan" :key="c.catalogue"
                  :class="{ 'row-active': jinanSyncData.current_catalogue === c.catalogue }">
                  <span class="list-name" :title="c.catalogue_name">{{ c.catalogue_name || '—' }}</span>
                  <span>
                    <span v-if="c.status === 'completed'" class="badge badge-green">✓</span>
                    <span v-else-if="c.status === 'running'" class="badge badge-blue">●</span>
                    <span v-else-if="c.status === 'interrupted'" class="badge badge-yellow">⚠</span>
                    <span v-else class="badge badge-gray">—</span>
                  </span>
                  <span class="list-num">{{ (c.docs_written || 0).toLocaleString() }}</span>
                  <span class="list-date">{{ c.period || '—' }}</span>
                </div>
              </div>
              <div class="list-pagination" v-if="totalJinanPages > 1">
                <button class="pg-btn" @click="jinanPage--" :disabled="jinanPage <= 1">‹</button>
                <span class="pg-info">{{ jinanPage }}/{{ totalJinanPages }}</span>
                <button class="pg-btn" @click="jinanPage++" :disabled="jinanPage >= totalJinanPages">›</button>
              </div>
              <div class="progress-wrap" v-if="jinanSyncData.current_catalogue && jinanSyncData.status === 'running'">
                <div class="progress-bar">
                  <div class="progress-fill progress-fill-jn" :style="{ width: getJinanPercent().toFixed(1) + '%' }"></div>
                </div>
                <div class="progress-info">
                  <span>{{ jinanSyncData.current_catalogue_name || jinanSyncData.current_catalogue }}</span>
                  <span>{{ jinanSyncData.current_page }}/{{ jinanSyncData.total_pages }}页</span>
                  <span class="pct-active">{{ getJinanPercent().toFixed(1) }}%</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 重庆 -->
      <div class="sync-card" :class="{ 'sync-card-running': chongqingSyncData.status === 'running' }">
        <div class="sync-card-bar sync-bar-cq"></div>
        <div class="sync-card-content">
          <div class="sync-card-header">
            <div class="sync-card-title-row">
              <span class="sync-province-tag tag-cq">重庆</span>
              <span class="sync-card-title">工程造价材料信息</span>
            </div>
            <div class="sync-badges">
              <span v-if="chongqingSyncData.has_incremental === true" class="badge badge-green">有新数据</span>
              <span v-else-if="chongqingSyncData.has_incremental === false && chongqingSyncData.es_latest_period" class="badge badge-blue">{{ chongqingSyncData.es_latest_period }}</span>
              <span v-else-if="chongqingSyncData.es_latest_period" class="badge badge-blue">{{ chongqingSyncData.es_latest_period }}</span>
            </div>
          </div>
          <div class="sync-card-meta">{{ formatDur(chongqingSyncData.duration_sec) }} · {{ chongqingSyncData.last_updated || '—' }}</div>

          <div class="sync-card-body">
            <div class="sync-info-col">
              <svg class="ring" viewBox="0 0 100 100">
                <circle class="ring-bg" cx="50" cy="50" r="40" />
                <circle class="ring-fill ring-cq" cx="50" cy="50" r="40"
                  :stroke-dasharray="251.327"
                  :stroke-dashoffset="251.327 * (1 - chongqingRing.pct / 100)" />
                <text class="ring-pct" x="50" y="46" text-anchor="middle" font-size="16" font-weight="700">{{ chongqingRing.done }}/{{ chongqingRing.total }}</text>
                <text class="ring-sub" x="50" y="64" text-anchor="middle" font-size="10">{{ chongqingSyncData.status === 'completed' && chongqingSyncData.completed_counties === 0 ? '未开始' : (chongqingSyncData.status === 'completed' && chongqingSyncData.completed_counties < chongqingSyncData.total_counties ? '部分完成' : (chongqingRing.pct >= 100 ? (chongqingSyncData.completed_counties > 0 ? '全部完成' : '已完成') : '进行中')) }}</text>
              </svg>
              <div class="sync-status-row">
                <span v-if="chongqingSyncData.status === 'running'" class="badge badge-blue">● 同步中</span>
                <span v-else-if="chongqingSyncData.status === 'completed' && chongqingSyncData.completed_counties === 0" class="badge badge-red">✗ 全部失败</span>
                <span v-else-if="chongqingSyncData.status === 'completed' && chongqingSyncData.completed_counties < chongqingSyncData.total_counties" class="badge badge-yellow">⚠ 部分完成 {{ chongqingSyncData.completed_counties }}/{{ chongqingSyncData.total_counties }}</span>
                <span v-else-if="chongqingSyncData.status === 'completed'" class="badge badge-green">✓ 全部完成</span>
                <span v-else-if="chongqingSyncData.status === 'interrupted'" class="badge badge-yellow">⚠ 已中断</span>
                <span v-else-if="chongqingSyncData.status === 'error'" class="badge badge-red">✗ 出错</span>
                <span v-else class="badge badge-gray">— 无记录</span>
              </div>
              <div class="sync-doc-count">{{ (chongqingSyncData.total_docs || 0).toLocaleString() }} 条文档</div>
            </div>

            <div class="sync-list-col">
              <div class="list-header"><span>区县</span><span>状态</span><span>文档数</span><span>期数</span></div>
              <div class="list-scroll">
                <div class="list-row" v-for="c in pagedChongqing" :key="c.county"
                  :class="{ 'row-active': chongqingSyncData.current_county === c.county && chongqingSyncData.status === 'running' }">
                  <span class="list-name">{{ c.county }}</span>
                  <span>
                    <span v-if="chongqingSyncData.current_county === c.county && chongqingSyncData.status === 'running'" class="badge badge-blue">●</span>
                    <span v-else-if="c.status === 'completed'" class="badge badge-green">✓</span>
                    <span v-else-if="c.status === 'failed' || c.status === 'error'" class="badge badge-red">✗</span>
                    <span v-else class="badge badge-gray">—</span>
                  </span>
                  <span class="list-num">{{ (c.docs_written || 0).toLocaleString() }}</span>
                  <span class="list-date">{{ c.period || '—' }}</span>
                </div>
              </div>
              <div class="list-pagination" v-if="totalChongqingPages > 1">
                <button class="pg-btn" @click="chongqingPage--" :disabled="chongqingPage <= 1">‹</button>
                <span class="pg-info">{{ chongqingPage }}/{{ totalChongqingPages }}</span>
                <button class="pg-btn" @click="chongqingPage++" :disabled="chongqingPage >= totalChongqingPages">›</button>
              </div>
              <div class="progress-wrap" v-if="chongqingSyncData.current_county && chongqingSyncData.status === 'running'">
                <div class="progress-bar">
                  <div class="progress-fill progress-fill-cq" :style="{ width: getChongqingPercent().toFixed(1) + '%' }"></div>
                </div>
                <div class="progress-info">
                  <span>{{ chongqingSyncData.current_county }}</span>
                  <span>{{ chongqingSyncData.current_page }}/{{ chongqingSyncData.total_pages }}页</span>
                  <span class="pct-active">{{ getChongqingPercent().toFixed(1) }}%</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 河南（按期期刊同步） -->
      <div class="sync-card" :class="{ 'sync-card-running': henanSyncData.status === 'running' }">
        <div class="sync-card-bar sync-bar-hn"></div>
        <div class="sync-card-content">
          <div class="sync-card-header">
            <div class="sync-card-title-row">
              <span class="sync-province-tag tag-hn">河南</span>
              <span class="sync-card-title">工程造价材料信息</span>
            </div>
            <div class="sync-badges">
              <span v-if="henanSyncData.has_incremental === true" class="badge badge-green">有新数据</span>
              <span v-else-if="henanSyncData.es_latest_period" class="badge badge-blue">{{ henanSyncData.es_latest_period }}</span>
            </div>
          </div>
          <div class="sync-card-meta">{{ formatDur(henanSyncData.duration_sec) }} · {{ henanSyncData.last_updated || '—' }}</div>

          <div class="sync-card-body">
            <div class="sync-info-col">
              <svg class="ring" viewBox="0 0 100 100">
                <circle class="ring-bg" cx="50" cy="50" r="40" />
                <circle class="ring-fill ring-hn" cx="50" cy="50" r="40"
                  :stroke-dasharray="251.327"
                  :stroke-dashoffset="251.327 * (1 - henanRing.pct / 100)" />
                <text class="ring-pct" x="50" y="46" text-anchor="middle" font-size="18" font-weight="700">{{ henanRing.done }}/{{ henanRing.total }}</text>
                <text class="ring-sub" x="50" y="64" text-anchor="middle" font-size="10">期数</text>
              </svg>
              <div class="sync-status-row">
                <span v-if="henanSyncData.status === 'running'" class="badge badge-blue">● 同步中</span>
                <span v-else-if="henanSyncData.status === 'error'" class="badge badge-red">✗ 出错</span>
                <span v-else class="badge badge-green">✓ 全部完成</span>
              </div>
              <div class="sync-doc-count">{{ (henanSyncData.total_docs || 0).toLocaleString() }} 条文档</div>
            </div>

            <div class="sync-list-col">
              <div class="list-header"><span>期数</span><span>状态</span><span>文档数</span><span>发布日期</span></div>
              <div class="list-scroll">
                <div class="list-row" v-for="p in henanSyncData.period_details || []" :key="p.period">
                  <span class="list-name">{{ p.period }}</span>
                  <span>
                    <span v-if="p.status === 'completed'" class="badge badge-green">✓</span>
                    <span v-else-if="p.status === 'running'" class="badge badge-blue">●</span>
                    <span v-else class="badge badge-gray">—</span>
                  </span>
                  <span class="list-num">{{ (p.docs_written || 0).toLocaleString() }}</span>
                  <span class="list-date">{{ p.publish_date || '—' }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 菏泽（按期期刊同步） -->
      <div class="sync-card" :class="{ 'sync-card-running': hezeSyncData.status === 'running' }">
        <div class="sync-card-bar sync-bar-hz"></div>
        <div class="sync-card-content">
          <div class="sync-card-header">
            <div class="sync-card-title-row">
              <span class="sync-province-tag tag-hz">菏泽</span>
              <span class="sync-card-title">工程造价材料信息</span>
            </div>
            <div class="sync-badges">
              <span v-if="hezeSyncData.has_incremental === true" class="badge badge-green">有新数据</span>
              <span v-else-if="hezeSyncData.es_latest_period" class="badge badge-blue">{{ hezeSyncData.es_latest_period }}</span>
            </div>
          </div>
          <div class="sync-card-meta">{{ formatDur(hezeSyncData.duration_sec) }} · {{ hezeSyncData.last_updated || '—' }}</div>

          <div class="sync-card-body">
            <div class="sync-info-col">
              <svg class="ring" viewBox="0 0 100 100">
                <circle class="ring-bg" cx="50" cy="50" r="40" />
                <circle class="ring-fill ring-hz" cx="50" cy="50" r="40"
                  :stroke-dasharray="251.327"
                  :stroke-dashoffset="251.327 * (1 - hezeRing.pct / 100)" />
                <text class="ring-pct" x="50" y="46" text-anchor="middle" font-size="18" font-weight="700">{{ hezeRing.done }}/{{ hezeRing.total }}</text>
                <text class="ring-sub" x="50" y="64" text-anchor="middle" font-size="10">期数</text>
              </svg>
              <div class="sync-status-row">
                <span v-if="hezeSyncData.status === 'running'" class="badge badge-blue">● 同步中</span>
                <span v-else-if="hezeSyncData.status === 'error'" class="badge badge-red">✗ 出错</span>
                <span v-else class="badge badge-green">✓ 全部完成</span>
              </div>
              <div class="sync-doc-count">{{ (hezeSyncData.total_docs || 0).toLocaleString() }} 条文档</div>
            </div>

            <div class="sync-list-col">
              <div class="list-header"><span>期数</span><span>状态</span><span>文档数</span><span>发布日期</span></div>
              <div class="list-scroll">
                <div class="list-row" v-for="p in hezeSyncData.period_details || []" :key="p.period">
                  <span class="list-name">{{ p.period }}</span>
                  <span>
                    <span v-if="p.status === 'completed'" class="badge badge-green">✓</span>
                    <span v-else-if="p.status === 'running'" class="badge badge-blue">●</span>
                    <span v-else class="badge badge-gray">—</span>
                  </span>
                  <span class="list-num">{{ (p.docs_written || 0).toLocaleString() }}</span>
                  <span class="list-date">{{ p.publish_date || '—' }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

    </div>

    <div v-if="loading" class="health-loading">
      <SkeletonCard :lines="5" :hide-footer="true" />
    </div>
    <EmptyState v-else-if="!Object.keys(data || {}).length"
      icon="📊" title="暂无数据" message="请稍后再试或检查上游接口" />
    <div v-if="error" class="health-error">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, computed, watch } from 'vue'
import axios from 'axios'
import { markRaw } from 'vue'
import * as echarts from 'echarts'
import SkeletonCard from './SkeletonCard.vue'
import EmptyState from './EmptyState.vue'

const API = import.meta.env.VITE_API_URL || '/api'
const loading = ref(false)
const error = ref('')
const showCardDetail = ref(false)  // 6 城大卡详情默认收起，仅显示概览
const currentTime = ref('')
const data = ref({
  total_docs: 0, province_count: 0, stale_provinces: 0,
  daily: [], provinces: []
})
const syncData = ref({})
const sichuanSyncData = ref({})
const rizhaoSyncData = ref({})
const jinanSyncData = ref({})
const chongqingSyncData = ref({})
const henanSyncData = ref({})
const hezeSyncData = ref({})
const xaPollTimer = ref(null)
const scPollTimer = ref(null)
const rzPollTimer = ref(null)
const jinanPollTimer = ref(null)
const chongqingPollTimer = ref(null)
const henanPollTimer = ref(null)
const hezePollTimer = ref(null)
const jinanPage = ref(1)
const countyPage = ref(1)
const sichuanPage = ref(1)
const rizhaoPage = ref(1)
const chongqingPage = ref(1)
const PAGE_SIZE = 10

const SICHUAN_AREAS = [
  '成都市','绵阳市','自贡市','攀枝花市','泸州市','德阳市','广元市','遂宁市',
  '内江市','乐山市','资阳市','宜宾市','南充市','达州市','雅安市','阿坝州','甘孜州','凉山州','广安市','巴中市','眉山市'
]

const CQ_COUNTIES = [
  '主城区','万州区','涪陵区','黔江区','长寿区','江津区','合川区','永川区',
  '南川区','梁平区','城口县','丰都县','垫江县','忠县','开州区','云阳县',
  '奉节县','巫山县','巫溪县','石柱县','秀山县','酉阳县','大足区','綦江区',
  '万盛经开区','双桥经开区','铜梁区','璧山区','彭水县1','彭水县2','彭水县3',
  '荣昌区1','荣昌区2','潼南区','武隆区'
]

function updateTime() {
  const now = new Date()
  const pad = n => String(n).padStart(2, '0')
  currentTime.value = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
}

const sichuanRing = computed(() => {
  const details = sichuanSyncData.value.area_details || []
  const filtered = details.filter(d => d.area)
  const total = SICHUAN_AREAS.length
  const done = filtered.filter(d => d.status === 'completed' || d.current_page >= d.total_pages).length
  const status = sichuanSyncData.value.status || ''
  if (status === 'completed') return { done: total, total, pct: 100 }
  return { done, total, pct: Math.round(done / total * 100) }
})

const chongqingRing = computed(() => {
  const total = chongqingSyncData.value.total_counties || 37
  const done = chongqingSyncData.value.completed_counties || 0
  const status = chongqingSyncData.value.status || ''
  if (status === 'completed') {
    if (done === 0) return { done: 0, total, pct: 0 }
    return { done, total, pct: total > 0 ? Math.round(done / total * 100) : 0 }
  }
  return { done, total, pct: total > 0 ? Math.round(done / total * 100) : 0 }
})

// 河南/菏泽是按期期刊同步，用 period_details 计算环状圈
const henanRing = computed(() => {
  const total = henanSyncData.value.total_periods || 0
  const done = henanSyncData.value.completed_periods || 0
  const pct = total > 0 ? Math.round(done / total * 100) : 0
  return { done, total, pct }
})
const hezeRing = computed(() => {
  const total = hezeSyncData.value.total_periods || 0
  const done = hezeSyncData.value.completed_periods || 0
  const pct = total > 0 ? Math.round(done / total * 100) : 0
  return { done, total, pct }
})

function getCountyPercent() {
  const cp = syncData.value.current_page || 0
  const tp = syncData.value.total_pages || 1
  return tp > 0 ? Math.round(cp / tp * 100 * 10) / 10 : 0
}

function getSichuanPercent() {
  const cp = sichuanSyncData.value.current_page || 0
  const tp = sichuanSyncData.value.total_pages || 1
  return tp > 0 ? Math.round(cp / tp * 100 * 10) / 10 : 0
}

function getRizhaoPercent() {
  const cp = rizhaoSyncData.value.current_page || 0
  const tp = rizhaoSyncData.value.total_pages || 1
  return tp > 0 ? Math.round(cp / tp * 100 * 10) / 10 : 0
}

function formatDur(sec) {
  if (!sec) return '—'
  if (sec < 60) return Math.round(sec) + 's'
  if (sec < 3600) return Math.round(sec / 60) + 'm'
  return (sec / 3600).toFixed(1) + 'h'
}

const pagedCounties = computed(() => {
  const list = syncData.value.county_details || []
  const start = (countyPage.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})
const totalCountyPages = computed(() => Math.ceil((syncData.value.county_details || []).length / PAGE_SIZE))

const pagedSichuan = computed(() => {
  const list = (sichuanSyncData.value.area_details || []).filter(d => d.area)
  const start = (sichuanPage.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})
const totalSichuanPages = computed(() => Math.ceil((sichuanSyncData.value.area_details || []).filter(d => d.area).length / PAGE_SIZE))

const rizhaoRing = computed(() => {
  const details = rizhaoSyncData.value.tab_details || []
  const total = 3
  const done = details.filter(d => d.status === 'completed' || d.status === 'running' || d.current_page >= d.total_pages).length
  const status = rizhaoSyncData.value.status || ''
  if (status === 'completed' && done === total) return { done: total, total, pct: 100 }
  if (!details.length && !status) return { done: 0, total, pct: 0 }
  return { done, total, pct: Math.round(done / total * 100) }
})

const rizhaoRingAllDone = computed(() => {
  const details = rizhaoSyncData.value.tab_details || []
  if (details.length < 3) return false
  return details.every(d => d.status === 'completed' || d.current_page >= d.total_pages)
})

const pagedRizhao = computed(() => {
  const list = rizhaoSyncData.value.tab_details || []
  const start = (rizhaoPage.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})
const totalRizhaoPages = computed(() => Math.ceil((rizhaoSyncData.value.tab_details || []).length / PAGE_SIZE))

const jinanRing = computed(() => {
  const details = jinanSyncData.value.catalogue_details || []
  const total = details.length || 41
  const done = details.filter(d => d.status === 'completed').length
  const status = jinanSyncData.value.status || ''
  if (status === 'completed' || done >= total) return { done: total, total, pct: 100 }
  return { done, total, pct: Math.round(done / total * 100) }
})
const jinanRingAllDone = computed(() => {
  const details = jinanSyncData.value.catalogue_details || []
  if (!details.length) return false
  return details.every(d => d.status === 'completed')
})
const pagedJinan = computed(() => {
  const list = jinanSyncData.value.catalogue_details || []
  const start = (jinanPage.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})
const totalJinanPages = computed(() => Math.ceil((jinanSyncData.value.catalogue_details || []).length / PAGE_SIZE))

const pagedChongqing = computed(() => {
  const list = chongqingSyncData.value.county_details || []
  const start = (chongqingPage.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})
const totalChongqingPages = computed(() => Math.ceil((chongqingSyncData.value.county_details || []).filter(d => d.county).length / PAGE_SIZE))

// 重庆列表数据变化时重置页码，避免翻页闪烁
watch(() => chongqingSyncData.value.county_details, () => {
  chongqingPage.value = 1
})

function getJinanPercent() {
  const cp = jinanSyncData.value.current_page || 0
  const tp = jinanSyncData.value.total_pages || 1
  return tp > 0 ? Math.round(cp / tp * 100 * 10) / 10 : 0
}

function getChongqingPercent() {
  const cp = chongqingSyncData.value.current_page || 0
  const tp = chongqingSyncData.value.total_pages || 1
  return tp > 0 ? Math.round(cp / tp * 100 * 10) / 10 : 0
}

async function pollXianSync() {
  if (syncData.value?.status === 'completed') {
    if (xaPollTimer.value) { clearInterval(xaPollTimer.value); xaPollTimer.value = null }
    return
  }
  try {
    const res = await axios.get(`${API}/stats/xian-sync-progress`)
    if (res.data) syncData.value = res.data
  } catch (e) { /* silent */ }
  if (syncData.value?.status === 'completed' && xaPollTimer.value) {
    clearInterval(xaPollTimer.value); xaPollTimer.value = null
  }
}

async function pollSichuanSync() {
  if (sichuanSyncData.value?.status === 'completed') {
    if (scPollTimer.value) { clearInterval(scPollTimer.value); scPollTimer.value = null }
    return
  }
  try {
    const res2 = await axios.get(`${API}/stats/sichuan-sync-progress`)
    if (res2.data) sichuanSyncData.value = res2.data
  } catch (e) { /* silent */ }
  if (sichuanSyncData.value?.status === 'completed' && scPollTimer.value) {
    clearInterval(scPollTimer.value); scPollTimer.value = null
  }
}

async function pollRizhaoSync() {
  if (rizhaoRingAllDone.value) {
    if (rzPollTimer.value) { clearInterval(rzPollTimer.value); rzPollTimer.value = null }
    return
  }
  try {
    const rzRes = await axios.get(`${API}/stats/rizhao-sync-progress`)
    if (rzRes.data) rizhaoSyncData.value = rzRes.data
  } catch (e) { /* silent */ }
  if (rizhaoRingAllDone.value && rzPollTimer.value) {
    clearInterval(rzPollTimer.value); rzPollTimer.value = null
  }
}

async function pollChongqingSync() {
  try {
    const res = await axios.get(`${API}/stats/chongqing-sync-progress`)
    if (res.data) chongqingSyncData.value = res.data
  } catch (e) { /* silent */ }
  const done = chongqingSyncData.value?.completed_counties || 0
  const total = chongqingSyncData.value?.total_counties || 37
  const status = chongqingSyncData.value?.status || ''
  if ((status === 'completed' || status === 'interrupted') && chongqingPollTimer.value) {
    clearInterval(chongqingPollTimer.value)
    chongqingPollTimer.value = null
  }
}

async function pollJinanSync() {
  if (jinanRingAllDone.value) {
    if (jinanPollTimer.value) { clearInterval(jinanPollTimer.value); jinanPollTimer.value = null }
    return
  }
  try {
    const res = await axios.get(`${API}/stats/jinan-sync-progress`)
    if (res.data) jinanSyncData.value = res.data
  } catch (e) { /* silent */ }
  if (jinanRingAllDone.value && jinanPollTimer.value) {
    clearInterval(jinanPollTimer.value); jinanPollTimer.value = null
  }
}

async function pollHenanSync() {
  try {
    const res = await axios.get(`${API}/stats/henan-sync-progress`)
    if (res.data) henanSyncData.value = res.data
  } catch (e) { /* silent */ }
  if (henanSyncData.value.status === 'ok' && henanPollTimer.value) {
    clearInterval(henanPollTimer.value); henanPollTimer.value = null
  }
}

async function pollHezeSync() {
  try {
    const res = await axios.get(`${API}/stats/heze-sync-progress`)
    if (res.data) hezeSyncData.value = res.data
  } catch (e) { /* silent */ }
  if (hezeSyncData.value.status === 'ok' && hezePollTimer.value) {
    clearInterval(hezePollTimer.value); hezePollTimer.value = null
  }
}

async function loadData() {
  loading.value = true
  error.value = ''
  updateTime()
  try {
    const healthRes = await axios.get(`${API}/stats/data-health`)
    data.value = healthRes.data || {}
  } catch (e) {
    console.warn('data-health 加载失败:', e.message)
  }
  try {
    const syncRes = await axios.get(`${API}/stats/xian-sync-progress`)
    if (syncRes.data) syncData.value = syncRes.data
  } catch (e) {
    console.warn('sync-progress 加载失败:', e.message)
  }
  try {
    const scRes = await axios.get(`${API}/stats/sichuan-sync-progress`)
    if (scRes.data) sichuanSyncData.value = scRes.data
  } catch (e) {
    console.warn('sichuan-sync-progress 加载失败:', e.message)
  }
  try {
    const rzRes = await axios.get(`${API}/stats/rizhao-sync-progress`)
    if (rzRes.data) rizhaoSyncData.value = rzRes.data
  } catch (e) {
    console.warn('rizhao-sync-progress 加载失败:', e.message)
  }
  try {
    const jinanRes = await axios.get(`${API}/stats/jinan-sync-progress`)
    if (jinanRes.data) jinanSyncData.value = jinanRes.data
  } catch (e) {
    console.warn('jinan-sync-progress 加载失败:', e.message)
  }
  try {
    const cqRes = await axios.get(`${API}/stats/chongqing-sync-progress`)
    if (cqRes.data) chongqingSyncData.value = cqRes.data
  } catch (e) {
    console.warn('chongqing-sync-progress 加载失败:', e.message)
  }
  try {
    const hnRes = await axios.get(`${API}/stats/henan-sync-progress`)
    if (hnRes.data) henanSyncData.value = hnRes.data
  } catch (e) {
    console.warn('henan-sync-progress 加载失败:', e.message)
  }
  try {
    const hzRes = await axios.get(`${API}/stats/heze-sync-progress`)
    if (hzRes.data) hezeSyncData.value = hzRes.data
  } catch (e) {
    console.warn('heze-sync-progress 加载失败:', e.message)
  }
  error.value = ''
  loading.value = false
  await nextTick()
  renderDailyChart()
}

function renderDailyChart() {
  const el = document.getElementById('dailyTrendChart')
  if (!el || !data.value.daily?.length) return
  if (dailyChart.value) { dailyChart.value.dispose(); dailyChart.value = null }
  const chart = markRaw(echarts.init(el))
  dailyChart.value = chart

  const buckets = data.value.daily
  const labels = buckets.map(b => b.date.slice(5))
  const values = buckets.map(b => b.count)
  const isZero = v => v === 0

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0d1117', borderColor: '#334155', borderWidth: 1,
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: p => `<b style="color:#60a5fa">${p[0].name}</b><br/>数量: <b style="color:#34d399">${p[0].value.toLocaleString()}</b>`
    },
    grid: { left: '3%', right: '3%', bottom: '10%', top: '14%', containLabel: true },
    xAxis: {
      type: 'category', data: labels,
      axisLabel: { color: '#94a3b8', fontSize: 10, rotate: 45, interval: 0 },
      axisLine: { lineStyle: { color: '#334155' } },
      axisTick: { show: false },
      splitLine: { show: false }
    },
    yAxis: {
      name: '文档数', nameTextStyle: { color: '#64748b', fontSize: 10, padding: [0, 0, 0, 30] },
      type: 'value',
      axisLabel: { color: '#64748b', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } }
    },
    series: [{
      type: 'bar', data: values,
      itemStyle: {
        color: p => isZero(p.value) ? '#1e293b' : new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#38bdf8' },
          { offset: 1, color: '#6366f1' }
        ])
      },
      barMaxWidth: 20,
      emphasis: {
        itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#7dd3fc' },
          { offset: 1, color: '#818cf8' }
        ]) }
      }
    }],
  })
  if (dailyResizeHandler) window.removeEventListener('resize', dailyResizeHandler)
  dailyResizeHandler = () => chart.resize()
  window.addEventListener('resize', dailyResizeHandler)
}

const dailyChart = ref(null)
let dailyResizeHandler = null
let timeTimer = null

onMounted(async () => {
  updateTime()
  timeTimer = setInterval(updateTime, 1000)
  await loadData()
  xaPollTimer.value = setInterval(pollXianSync, 5000)
  scPollTimer.value = setInterval(pollSichuanSync, 7000)
  rzPollTimer.value = setInterval(pollRizhaoSync, 9000)
  jinanPollTimer.value = setInterval(pollJinanSync, 11000)
  chongqingPollTimer.value = setInterval(pollChongqingSync, 6000)
  henanPollTimer.value = setInterval(pollHenanSync, 13000)
  hezePollTimer.value = setInterval(pollHezeSync, 13000)
})
onUnmounted(() => {
  if (xaPollTimer.value) clearInterval(xaPollTimer.value)
  if (scPollTimer.value) clearInterval(scPollTimer.value)
  if (rzPollTimer.value) clearInterval(rzPollTimer.value)
  if (jinanPollTimer.value) clearInterval(jinanPollTimer.value)
  if (chongqingPollTimer.value) clearInterval(chongqingPollTimer.value)
  if (henanPollTimer.value) clearInterval(henanPollTimer.value)
  if (hezePollTimer.value) clearInterval(hezePollTimer.value)
  if (dailyResizeHandler) window.removeEventListener('resize', dailyResizeHandler)
  if (timeTimer) clearInterval(timeTimer)
})
</script>

<style scoped>
/* ===== 整体布局 ===== */
.health-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 20px;
  padding-top: 16px;
  min-height: 100vh;
  background: linear-gradient(180deg, #0c1222 0%, #111827 100%);
  position: static;   /* was fixed — let it flow with document */
  z-index: 10;
  box-sizing: border-box;
}

/* ===== 顶部标题栏 ===== */
.health-header {
  background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f172a 100%);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 0;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}
.header-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.header-icon {
  font-size: 28px;
  width: 48px;
  height: 48px;
  background: rgba(255,255,255,0.06);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255,255,255,0.08);
}
.header-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.health-title {
  font-size: 18px;
  font-weight: 800;
  color: #f1f5f9;
  letter-spacing: 2px;
  font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace;
  text-shadow: 0 2px 12px rgba(56,189,248,0.2);
}
.health-subtitle {
  font-size: 12px;
  color: var(--text-3);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.header-time {
  font-size: 13px;
  color: #475569;
  font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace;
  letter-spacing: 1px;
}
.btn-refresh {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  background: rgba(59,130,246,0.15);
  border: 1px solid rgba(59,130,246,0.3);
  border-radius: 8px;
  font-size: 13px;
  color: #60a5fa;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-refresh:hover {
  background: rgba(59,130,246,0.25);
  border-color: rgba(59,130,246,0.5);
  box-shadow: 0 0 16px rgba(59,130,246,0.2);
}
.btn-refresh.spinning { opacity: 0.6; pointer-events: none; }
.refresh-icon { font-size: 14px; }

/* ===== 四个汇总指标卡 ===== */
.health-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.stat-card {
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 0;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.25);
  transition: transform var(--transition), box-shadow var(--transition), border-color var(--transition);
  position: relative;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 40px rgba(0,0,0,0.35), 0 0 0 1px rgba(56,189,248,0.06);
  border-color: rgba(56,189,248,0.18);
}
.stat-card-inner {
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  position: relative;
}
.stat-icon {
  font-size: 24px;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-card-primary .stat-icon { background: rgba(59,130,246,0.15); }
.stat-card-cyan .stat-icon { background: rgba(6,182,212,0.15); }
.stat-card-warning .stat-icon { background: rgba(245,158,11,0.15); }
.stat-card-magenta .stat-icon { background: rgba(168,85,247,0.15); }

.stat-content { flex: 1; min-width: 0; }
.stat-label {
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stat-num {
  font-size: 36px;
  font-weight: 800;
  color: var(--primary);
  line-height: 1;
  font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace;
  text-shadow: 0 0 20px rgba(56,189,248,0.4);
  display: block;
}

.stat-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.stat-unit {
  font-size: 13px;
  font-weight: 400;
  margin-left: 4px;
  color: #475569;
}
.stat-glow {
  position: absolute;
  top: 0;
  right: 0;
  width: 80px;
  height: 60px;
  border-radius: 0 14px 0 0;
  pointer-events: none;
}
.stat-card-primary .stat-glow { background: radial-gradient(ellipse at top right, rgba(59,130,246,0.12), transparent 70%); }
.stat-card-cyan .stat-glow { background: radial-gradient(ellipse at top right, rgba(6,182,212,0.12), transparent 70%); }
.stat-card-warning .stat-glow { background: radial-gradient(ellipse at top right, rgba(245,158,11,0.12), transparent 70%); }
.stat-card-magenta .stat-glow { background: radial-gradient(ellipse at top right, rgba(168,85,247,0.12), transparent 70%); }

.stat-card-warning.stat-alert { border-color: rgba(245,158,11,0.3); }
.stat-card-warning.stat-alert .stat-value { color: var(--status-warn); }
.stat-card-magenta.stat-alert { border-color: rgba(168,85,247,0.3); }
.stat-card-magenta.stat-alert .stat-value { color: #c084fc; }

.text-up { color: var(--status-ok) !important; }
.text-down { color: var(--status-alert) !important; }

/* ===== 图表面板 ===== */
.chart-panel {
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.25);
  flex-shrink: 0;
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.panel-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.panel-dot-blue { background: var(--primary); box-shadow: 0 0 8px rgba(56,189,248,0.5); }
.panel-title { font-size: 14px; font-weight: 700; color: #e2e8f0; }
.chart-legend { display: flex; gap: 16px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-3); }
.legend-dot { width: 10px; height: 10px; border-radius: 2px; background: linear-gradient(135deg, var(--primary), #6366f1); }
.chart-area { width: 100%; height: 320px; }

/* ===== 省份同步卡片网格 ===== */
.sync-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

/* 6 城大卡详情默认收起：仅显示 header + meta（总览信息） */
.sync-card-body { display: none; }
.health-page.show-card-detail .sync-card-body { display: block; }
.sync-card.show-card-detail,
.health-page.show-card-detail .sync-card { /* keep existing styles intact */ }

/* 收起状态下，body 隐藏，卡片 height 自动收缩 */
.sync-card {
  transition: box-shadow 0.2s, border-color 0.2s;
}
.sync-card-body {
  transition: max-height 0.3s ease;
}

/* 全局展开/收起 工具条 */
.sync-grid-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 4px 10px;
  margin-top: 6px;
}
.sync-grid-hint {
  font-size: 11px;
  color: var(--text-3);
}
.sync-grid-toggle {
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 6px;
  border: 1px solid rgba(56,189,248,0.25);
  background: rgba(56,189,248,0.06);
  color: var(--primary);
  cursor: pointer;
  font-weight: 600;
  transition: all 0.15s;
  font-family: inherit;
}
.sync-grid-toggle:hover {
  background: rgba(56,189,248,0.14);
  border-color: var(--primary);
}

/* ===== 同步卡片 ===== */
.sync-card {
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 0;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
  transition: transform var(--transition), box-shadow var(--transition), border-color var(--transition);
  display: flex;
  flex-direction: row;
  position: relative;
  min-height: 0;
}
.sync-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 40px rgba(0,0,0,0.3), 0 0 0 1px rgba(56,189,248,0.06);
  border-color: rgba(56,189,248,0.2);
}
.sync-card-running {
  border-color: rgba(56,189,248,0.2);
  box-shadow: 0 8px 32px rgba(0,0,0,0.2), 0 0 20px rgba(56,189,248,0.08);
}

/* 左侧彩色边条 */
.sync-card-bar {
  width: 4px;
  flex-shrink: 0;
  border-radius: 14px 0 0 14px;
}
.sync-bar-xa { background: linear-gradient(180deg, #3b82f6, #1d4ed8); }
.sync-bar-sc { background: linear-gradient(180deg, #06b6d4, #0891b2); }
.sync-bar-rz { background: linear-gradient(180deg, #10b981, #059669); }
.sync-bar-jn { background: linear-gradient(180deg, #8b5cf6, #7c3aed); }
.sync-bar-cq { background: linear-gradient(180deg, var(--status-warn), #d97706); }
.sync-bar-hn { background: linear-gradient(180deg, #ec4899, #be185d); }   /* 河南：玫红 */
.sync-bar-hz { background: linear-gradient(180deg, #f59e0b, #d97706); }   /* 菏泽：琥珀 */

.sync-card-content {
  flex: 1;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.sync-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 2px;
  flex-wrap: wrap;
}
.sync-card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.sync-province-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: 0.5px;
  color: #fff;
}
.tag-xa { background: linear-gradient(135deg, #3b82f6, #1d4ed8); }
.tag-sc { background: linear-gradient(135deg, #06b6d4, #0891b2); }
.tag-rz { background: linear-gradient(135deg, #10b981, #059669); }
.tag-jn { background: linear-gradient(135deg, #8b5cf6, #7c3aed); }
.tag-cq { background: linear-gradient(135deg, var(--status-warn), #d97706); }
.tag-hn { background: linear-gradient(135deg, #ec4899, #be185d); }
.tag-hz { background: linear-gradient(135deg, #f59e0b, #d97706); }

.sync-card-title { font-size: 14px; font-weight: 700; color: #e2e8f0; }
.sync-badges { display: flex; gap: 5px; flex-wrap: wrap; }
.sync-card-meta { font-size: 11px; color: #475569; margin-bottom: 12px; }

/* 卡片主体 */
.sync-card-body {
  display: flex;
  gap: 14px;
  align-items: stretch;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 左侧圆环信息列 */
.sync-info-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  flex-shrink: 0;
  width: 90px;
}
.ring { width: 76px; height: 76px; }
.ring-bg { fill: none; stroke: rgba(255,255,255,0.06); stroke-width: 8; }
.ring-fill {
  fill: none;
  stroke-width: 8;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 50% 50%;
  transition: stroke-dashoffset 0.6s ease;
}
.ring-xa { stroke: #3b82f6; }
.ring-sc { stroke: #06b6d4; }
.ring-rz { stroke: #10b981; }
.ring-jn { stroke: #8b5cf6; }
.ring-cq { stroke: var(--status-warn); }
.ring-hn { stroke: #ec4899; }
.ring-hz { stroke: #f59e0b; }
.ring-pct { font-size: 18px; font-weight: 700; fill: #f1f5f9; font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; }
.ring-sub { font-size: 10px; fill: var(--text-3); }
.sync-status-row { display: flex; justify-content: center; }
.sync-doc-count { font-size: 11px; color: #475569; text-align: center; }

/* 右侧列表列 */
.sync-list-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  /* fill parent height so pagination sticks to bottom */
  height: 100%;
}
.list-header {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 6px;
  padding: 0 4px 6px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  flex-shrink: 0;
}
.list-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  /* no fixed max-height — fills available space */
}
.list-scroll::-webkit-scrollbar { width: 3px; }
.list-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.list-scroll::-webkit-scrollbar-track { background: transparent; }
.list-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 6px;
  align-items: center;
  padding: 5px 4px;
  border-bottom: 1px solid rgba(255,255,255,0.03);
  font-size: 12px;
  border-radius: 4px;
  transition: background 0.15s;
}
.list-row:nth-child(even) { background: rgba(255,255,255,0.02); }
.list-row:last-child { border-bottom: none; }
.list-row.row-active { background: rgba(56,189,248,0.08) !important; }
.list-name { font-weight: 500; color: #cbd5e1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.list-num, .list-date { font-size: 11px; color: #475569; white-space: nowrap; }

/* 分页 - 吸底 */
.list-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px 8px;
  border-top: 1px solid rgba(255,255,255,0.04);
  flex-shrink: 0;
  background: rgba(15,23,42,0.7);
  border-radius: 0 0 8px 8px;
}
.pg-btn {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.15s;
}
.pg-btn:hover { background: rgba(255,255,255,0.1); color: #e2e8f0; }
.pg-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.pg-info { font-size: 12px; color: #475569; }

/* 进度条 */
.progress-wrap { margin-top: 8px; }
.progress-bar { height: 5px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; }
.progress-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}
.progress-fill-xa { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
.progress-fill-sc { background: linear-gradient(90deg, #06b6d4, #22d3ee); }
.progress-fill-rz { background: linear-gradient(90deg, #10b981, var(--status-ok)); }
.progress-fill-jn { background: linear-gradient(90deg, #8b5cf6, var(--purple)); }
.progress-fill-cq { background: linear-gradient(90deg, var(--status-warn), var(--status-warn)); }
.progress-info {
  display: flex;
  gap: 10px;
  font-size: 10px;
  color: #475569;
  margin-top: 3px;
}
.pct-active { color: #60a5fa; font-weight: 600; }

/* ===== 标签 ===== */
.badge {
  font-size: 10px;
  font-weight: 500;
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
  letter-spacing: 0.2px;
}
.badge-blue { background: rgba(59,130,246,0.15); color: #60a5fa; border: 1px solid rgba(59,130,246,0.2); }
.badge-green { background: rgba(16,185,129,0.15); color: var(--status-ok); border: 1px solid rgba(16,185,129,0.2); }
.badge-yellow { background: rgba(245,158,11,0.15); color: var(--status-warn); border: 1px solid rgba(245,158,11,0.2); }
.badge-red { background: rgba(239,68,68,0.15); color: var(--status-alert); border: 1px solid rgba(239,68,68,0.2); }
.badge-gray { background: rgba(255,255,255,0.05); color: #475569; border: 1px solid rgba(255,255,255,0.06); }

/* ===== 加载/错误 ===== */
.health-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 20px;
  color: #475569;
  font-size: 13px;
}
.health-error {
  text-align: center;
  padding: 20px;
  color: var(--status-alert);
  font-size: 13px;
}
.loading-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255,255,255,0.1);
  border-top-color: #60a5fa;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 6 城大卡详情默认收起（必须放在最后以覆盖同选择器） */
.sync-card-body { display: none; }
.health-page.show-card-detail .sync-card-body { display: flex; }
</style>
