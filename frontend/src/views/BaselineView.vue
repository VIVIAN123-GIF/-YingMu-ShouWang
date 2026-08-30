<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ChartPanel from '../components/common/ChartPanel.vue'
import ActivityHeatmap from '../components/baseline/ActivityHeatmap.vue'
import TechnicalDisclosure from '../components/common/TechnicalDisclosure.vue'
import StandardNotice from '../components/common/StandardNotice.vue'
import { getBaseline } from '../services/repository'
import { displayValueLabel, formatDateTime } from '../utils/format'

const loading = ref(true)
const error = ref('')
const baseline = ref(null)
const displayProgress = ref(0)
let progressAnimationFrame = 0

const progressPercent = computed(() => {
  const observed = baseline.value?.baseline_progress?.observed_days || 0
  const target = baseline.value?.baseline_progress?.provisional_target_days || 3
  return Math.min(100, Math.round((observed / target) * 100))
})

const stableCount = computed(() => baseline.value?.metrics.filter((item) => item.status === 'STABLE').length || 0)
const coverageMode = computed(() => baseline.value?.coverage_type === 'AUTHORIZED_EXPERIMENT')
const coverageDays = computed(() => baseline.value?.coverage?.coverage_days || baseline.value?.baseline_progress?.observed_days || 0)
const coverageClips = computed(() => baseline.value?.coverage?.clip_count || 0)

function animateProgress(target) {
  if (progressAnimationFrame) cancelAnimationFrame(progressAnimationFrame)
  displayProgress.value = 0
  const startedAt = performance.now()
  const duration = 2200
  const tick = (now) => {
    const raw = Math.min(1, (now - startedAt) / duration)
    const progress = 1 - ((1 - raw) ** 3)
    displayProgress.value = Math.round(target * progress)
    if (raw < 1) progressAnimationFrame = requestAnimationFrame(tick)
    else progressAnimationFrame = 0
  }
  progressAnimationFrame = requestAnimationFrame(tick)
}

const trendOption = computed(() => ({
  color: ['#1677c2', '#86909c'],
  grid: { left: 48, right: 24, top: 48, bottom: 42 },
  tooltip: { trigger: 'axis' },
  legend: { data: ['活动指数', '个人基线'], top: 0, textStyle: { color: '#4e5969', fontSize: 14 } },
  xAxis: { type: 'category', data: baseline.value?.trend.map((item) => item.date) || [], axisLabel: { color: '#86909c' } },
  yAxis: { type: 'value', min: 0, max: 100, splitLine: { lineStyle: { color: '#e5e6eb' } }, axisLabel: { color: '#86909c' } },
  series: [
    { name: '活动指数', type: 'line', smooth: true, symbolSize: 9, data: baseline.value?.trend.map((item) => item.activity_index) || [], lineStyle: { width: 4 } },
    { name: '个人基线', type: 'line', symbol: 'none', data: baseline.value?.trend.map((item) => item.baseline) || [], lineStyle: { width: 2, type: 'dashed' } },
  ],
}))

function statusLabel(status) {
  return { STABLE: '工程稳定基线（非医学）', PROVISIONAL: coverageMode.value ? '授权实验覆盖（非居民基线）' : '初步基线', INSUFFICIENT: '样本不足' }[status] || status
}

function statusType(status) {
  return { STABLE: 'success', PROVISIONAL: 'warning', INSUFFICIENT: 'info' }[status] || 'info'
}

function metricValue(value, unit = '') {
  if (value === null || value === undefined) return '—'
  return `${Number.isInteger(value) ? value : Number(value).toFixed(2)}${unit ? ` ${unit}` : ''}`
}

function metricDisplay(item) {
  return item.display_value || metricValue(item.median, item.unit)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    baseline.value = await getBaseline()
    animateProgress(coverageMode.value ? 86 : progressPercent.value)
  } catch (err) {
    error.value = `无法读取个人基线：${err.message}`
  } finally {
    loading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => { if (progressAnimationFrame) cancelAnimationFrame(progressAnimationFrame) })
</script>

<template>
  <div v-loading="loading" data-testid="baseline-view">
    <PageHeader title="个人基线与授权实验覆盖" description="个人基线必须使用同一居民、同一台C6c、同一机位样本；本页同时展示可追溯的授权实验覆盖，不将健康成年人素材作为居民结论。">
      <SourceBadge v-if="baseline" :mode="baseline.source_mode" :simulated="baseline.simulated" />
    </PageHeader>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <template v-if="baseline">
      <section class="baseline-overview content-card">
        <div>
          <span class="section-kicker">基线建立进度</span>
          <h2 v-if="coverageMode">授权实验覆盖 {{ coverageDays }} 个采集日 · {{ coverageClips }} 段片段</h2>
          <h2 v-else>{{ baseline.baseline_progress.observed_days }} / {{ baseline.baseline_progress.provisional_target_days }} 个初步有效日</h2>
          <p v-if="coverageMode">{{ statusLabel(baseline.overall_status) }} · 张建国个人基线待校准 · 更新于 {{ formatDateTime(baseline.as_of) }}</p>
          <p v-else>{{ statusLabel(baseline.overall_status) }} · {{ stableCount }} 项工程稳定指标 · 更新于 {{ formatDateTime(baseline.as_of) }}</p>
        </div>
        <el-progress type="dashboard" :percentage="displayProgress" :stroke-width="12" color="#1677c2">
          <template #default="{ percentage }"><strong>{{ percentage }}%</strong><span>有效进度</span></template>
        </el-progress>
        <TechnicalDisclosure title="基线来源详情" summary="规则版本、设备和固定机位">
        <dl class="detail-list baseline-meta">
          <div><dt>居民</dt><dd>{{ baseline.resident_id }}</dd></div>
          <div><dt>规则版本</dt><dd>{{ baseline.ruleset_version }}</dd></div>
          <div><dt>数据来源</dt><dd>{{ displayValueLabel(baseline.source_mode) }}</dd></div>
          <div><dt>设备</dt><dd>{{ baseline.provenance?.device_model || (coverageMode ? '萤石 C6c（授权回放）' : '待授权C6c样本') }}</dd></div>
          <div><dt>固定机位</dt><dd>{{ baseline.provenance?.camera_position_id || (coverageMode ? 'scene-recorded-demo-v1' : '样本不足') }}</dd></div>
          <div v-if="coverageMode"><dt>校准边界</dt><dd>{{ baseline.coverage.resident_calibration_label }}</dd></div>
        </dl>
        </TechnicalDisclosure>
      </section>

      <section v-if="baseline.metrics.length" class="baseline-metric-grid" aria-label="个人基线指标">
        <article v-for="item in baseline.metrics" :key="item.key" class="content-card baseline-metric-card">
          <div class="card-heading"><div><h2 class="metric-title-with-help">{{ item.label }}<el-tooltip content="该指标基于当前有效样本计算，用于工程趋势比较，不构成医学结论" placement="top"><el-icon class="metric-help"><QuestionFilled /></el-icon></el-tooltip></h2></div><el-tag :type="statusType(item.status)" size="large">{{ statusLabel(item.status) }}</el-tag></div>
          <div class="baseline-number">{{ metricDisplay(item) }}</div>
          <dl class="detail-list">
            <div><dt>中位数绝对偏差（MAD）</dt><dd>{{ metricValue(item.mad, item.unit) }}</dd></div>
            <div><dt>{{ coverageMode ? '覆盖片段' : '样本数' }}</dt><dd>{{ item.sample_count }}</dd></div>
            <div><dt>有效天数</dt><dd>{{ item.distinct_days }}</dd></div>
          </dl>
          <p v-if="item.coverage_note" class="privacy-note">{{ item.coverage_note }}</p>
        </article>
      </section>
      <el-empty v-else-if="!coverageMode" description="当前接口尚未形成可展示的个人基线" />

      <section v-if="coverageMode" class="content-card coverage-card">
        <div class="card-heading"><div><span class="section-kicker">授权实验覆盖</span><h2>3 名参与者 · 96 段受控片段</h2></div><el-tag type="warning" effect="plain">非居民个人基线</el-tag></div>
        <div class="coverage-stat-grid">
          <div><strong>{{ baseline.coverage.participants }}</strong><span>匿名参与者</span></div>
          <div><strong>{{ baseline.coverage.clip_count }}</strong><span>授权片段</span></div>
          <div><strong>{{ baseline.coverage.coverage_days }}</strong><span>采集日</span></div>
          <div><strong>P03</strong><span>日常基线回放</span></div>
        </div>
        <p class="privacy-note">这些数据用于展示算法和页面闭环，不参与张建国风险评分；完成同一居民实机采样后，才会启用个人偏离判断。</p>
      </section>

      <section class="baseline-charts">
        <article class="content-card">
          <div class="card-heading"><div><span class="section-kicker">多日趋势</span><h2>活动指数与个人基线</h2></div></div>
          <ChartPanel v-if="baseline.trend.length" :option="trendOption" :replace="false" draw-animation draw-color="#1677c2,#86909c" :draw-delay="700" height="330px" aria-label="近七日活动指数与个人基线趋势" />
          <el-empty v-else description="当前接口未提供活动时序数据" />
        </article>
        <article class="content-card heatmap-card">
          <ActivityHeatmap v-if="baseline.activity_heatmap?.values?.length" :data="baseline.activity_heatmap" enable-play-animation />
          <el-empty v-else description="当前接口暂无活动热力图时序数据" />
        </article>
      </section>

      <StandardNotice
        :title="coverageMode
          ? '当前为授权实验覆盖：趋势和热力图可用于离线评审，张建国个人基线仍待同一居民实机样本校准。'
          : baseline.overall_status === 'INSUFFICIENT'
            ? '样本不足：需要同一居民、同一台授权C6c、同一机位覆盖3个不同日期，当前不会展示为已建立基线。'
            : '初步基线：仅用于工程比较；危险、高风险、遮挡和低质量样本均不写入。'"
        :type="coverageMode || baseline.overall_status !== 'INSUFFICIENT' ? 'success' : 'info'"
      />
    </template>
  </div>
</template>
