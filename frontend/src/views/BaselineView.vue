<script setup>
import { computed, onMounted, ref } from 'vue'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ChartPanel from '../components/common/ChartPanel.vue'
import { getBaseline } from '../services/repository'
import { formatDateTime } from '../utils/format'

const loading = ref(true)
const error = ref('')
const baseline = ref(null)

const progressPercent = computed(() => {
  const observed = baseline.value?.baseline_progress?.observed_days || 0
  const target = baseline.value?.baseline_progress?.target_days || 7
  return Math.min(100, Math.round((observed / target) * 100))
})

const stableCount = computed(() => baseline.value?.metrics.filter((item) => item.status === 'STABLE').length || 0)

const trendOption = computed(() => ({
  color: ['#176b65', '#d39a42'],
  grid: { left: 48, right: 24, top: 48, bottom: 42 },
  tooltip: { trigger: 'axis' },
  legend: { data: ['活动指数', '个人基线'], top: 0, textStyle: { color: '#54635f', fontSize: 14 } },
  xAxis: { type: 'category', data: baseline.value?.trend.map((item) => item.date) || [], axisLabel: { color: '#64736f' } },
  yAxis: { type: 'value', min: 0, max: 100, splitLine: { lineStyle: { color: '#edf3f1' } }, axisLabel: { color: '#64736f' } },
  series: [
    { name: '活动指数', type: 'line', smooth: true, symbolSize: 9, data: baseline.value?.trend.map((item) => item.activity_index) || [], lineStyle: { width: 4 } },
    { name: '个人基线', type: 'line', symbol: 'none', data: baseline.value?.trend.map((item) => item.baseline) || [], lineStyle: { width: 2, type: 'dashed' } },
  ],
}))

const heatmapOption = computed(() => ({
  grid: { left: 70, right: 34, top: 18, bottom: 72 },
  tooltip: { formatter: ({ value }) => `${baseline.value.activity_heatmap.days[value[0]]} ${baseline.value.activity_heatmap.periods[value[1]]}<br/>活动指数：${value[2]}` },
  xAxis: { type: 'category', data: baseline.value?.activity_heatmap?.days || [], splitArea: { show: true }, axisLabel: { color: '#64736f' } },
  yAxis: { type: 'category', data: baseline.value?.activity_heatmap?.periods || [], splitArea: { show: true }, axisLabel: { color: '#64736f' } },
  visualMap: {
    min: 0, max: 100, calculable: false, orient: 'horizontal', left: 'center', bottom: 8,
    text: ['活动较多', '活动较少'], inRange: { color: ['#edf5f2', '#8bc1b3', '#176b65'] },
  },
  series: [{ name: '活动指数', type: 'heatmap', data: baseline.value?.activity_heatmap?.values || [], label: { show: true, color: '#243b36' } }],
}))

function statusLabel(status) {
  return { STABLE: '稳定基线', PROVISIONAL: '暂定基线', INSUFFICIENT: '样本不足' }[status] || status
}

function statusType(status) {
  return { STABLE: 'success', PROVISIONAL: 'warning', INSUFFICIENT: 'info' }[status] || 'info'
}

function metricValue(value, unit = '') {
  if (value === null || value === undefined) return '—'
  return `${Number.isInteger(value) ? value : Number(value).toFixed(2)}${unit ? ` ${unit}` : ''}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    baseline.value = await getBaseline()
  } catch (err) {
    error.value = `无法读取个人基线：${err.message}`
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" data-testid="baseline-view">
    <PageHeader title="个人基线与活动趋势" description="系统学习的是本人平常安全的状态，不使用统一人群阈值替代个人基线。">
      <SourceBadge v-if="baseline" :mode="baseline.source_mode" :simulated="baseline.simulated" :show-description="true" />
    </PageHeader>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <template v-if="baseline">
      <section class="baseline-overview content-card">
        <div>
          <span class="section-kicker">基线建立进度</span>
          <h2>{{ baseline.baseline_progress.observed_days }} / {{ baseline.baseline_progress.target_days }} 个有效日</h2>
          <p>已有 {{ stableCount }} 项指标达到稳定状态 · 更新于 {{ formatDateTime(baseline.as_of) }}</p>
        </div>
        <el-progress type="dashboard" :percentage="progressPercent" :stroke-width="12" color="#176b65">
          <template #default="{ percentage }"><strong>{{ percentage }}%</strong><span>有效进度</span></template>
        </el-progress>
        <dl class="detail-list baseline-meta">
          <div><dt>居民</dt><dd>{{ baseline.resident_id }}</dd></div>
          <div><dt>规则版本</dt><dd>{{ baseline.ruleset_version }}</dd></div>
          <div><dt>数据来源</dt><dd>{{ baseline.source_mode }}</dd></div>
        </dl>
      </section>

      <section v-if="baseline.metrics.length" class="baseline-metric-grid" aria-label="个人基线指标">
        <article v-for="item in baseline.metrics" :key="item.key" class="content-card baseline-metric-card">
          <div class="card-heading"><div><span class="section-kicker">{{ item.key }}</span><h2>{{ item.label }}</h2></div><el-tag :type="statusType(item.status)" size="large">{{ statusLabel(item.status) }}</el-tag></div>
          <div class="baseline-number">{{ metricValue(item.median, item.unit) }}</div>
          <dl class="detail-list">
            <div><dt>MAD</dt><dd>{{ metricValue(item.mad, item.unit) }}</dd></div>
            <div><dt>样本数</dt><dd>{{ item.sample_count }}</dd></div>
            <div><dt>有效天数</dt><dd>{{ item.distinct_days }}</dd></div>
          </dl>
        </article>
      </section>
      <el-empty v-else description="当前 API 尚未形成可展示的个人基线" />

      <section class="baseline-charts">
        <article class="content-card">
          <div class="card-heading"><div><span class="section-kicker">多日趋势</span><h2>活动指数与个人基线</h2></div></div>
          <ChartPanel v-if="baseline.trend.length" :option="trendOption" height="330px" aria-label="近七日活动指数与个人基线趋势" />
          <el-empty v-else description="当前 API 未提供活动时序数据，不使用 Mock 趋势补位" />
        </article>
        <article class="content-card heatmap-card">
          <div class="card-heading"><div><span class="section-kicker">日期 × 时段</span><h2>近七日活动热力图</h2></div><el-tag v-if="baseline.activity_heatmap && baseline.simulated" type="danger" effect="dark">模拟实验回放</el-tag></div>
          <ChartPanel v-if="baseline.activity_heatmap?.values?.length" :option="heatmapOption" height="330px" aria-label="近七日不同时段的模拟活动热力图" />
          <el-empty v-else description="当前 API 暂无活动热力图时序数据" />
          <p v-if="baseline.activity_heatmap" class="privacy-note">热力图只表达分时活动强度，不代表真实房间轨迹；房间区域数据待区域标定完成后接入。</p>
        </article>
      </section>

      <el-alert
        title="基线防污染：只有绿色正常时段且质量达标的样本可以进入基线；预警事件、遮挡和低质量数据不会自动写入。"
        type="success"
        show-icon
        :closable="false"
      />
    </template>
  </div>
</template>
