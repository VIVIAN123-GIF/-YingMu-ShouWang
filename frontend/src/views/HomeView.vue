<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CircleCheck, Connection, Monitor, QuestionFilled, Sunrise } from '@element-plus/icons-vue'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ChartPanel from '../components/common/ChartPanel.vue'
import { getDashboard } from '../services/repository'
import { displayValueLabel, domainLabel, formatDateTime, formatPercent, formatRiskScore, statusLabel } from '../utils/format'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const data = ref(null)
const animatedRiskWaterLevel = ref(0)
const fullRiskScores = computed(() => data.value?.risk_trend?.map((item) => Number(item.score)) || [])
const riskRingTone = computed(() => {
  const score = Number(data.value?.current_risk?.risk_score)
  if (!Number.isFinite(score) || score < 0.4) return 'low'
  if (score < 0.7) return 'mid'
  return 'high'
})
const riskWaterLevel = computed(() => {
  const score = Number(data.value?.current_risk?.risk_score)
  return Math.round((Number.isFinite(score) ? Math.min(1, Math.max(0, score)) : 0) * 100)
})

function animateRiskWaterLevel() {
  animatedRiskWaterLevel.value = 0
  window.setTimeout(() => { animatedRiskWaterLevel.value = riskWaterLevel.value }, 60)
}
const factorLabels = {
  fall_precursor_evidence: '起身后不稳证据',
  personal_baseline_deviation: '偏离个人基线',
  environment_interaction_risk: '人-环境交互风险',
  data_quality_downgrade: '数据质量降级',
  multi_scale_accumulation: '多时标累积',
  normal_fluctuation: '日常波动',
}
const assessmentLabels = { VALID: '完整评估', PARTIAL: '降级评估', INSUFFICIENT: '数据不足' }
const confidenceLabels = { LOW: '低', MEDIUM: '中', HIGH: '高' }
const baselineLabels = { INSUFFICIENT: '样本不足', PROVISIONAL: '初步基线', STABLE: '稳定工程基线' }
const degradationLabels = {
  HUMAN_EVIDENCE_INSUFFICIENT: '人体证据不足',
  PERSONAL_BASELINE_INSUFFICIENT: '个人基线不足',
  QUALITY_GATE_FAILED: '画面质量未通过',
  SCENE_CONTEXT_MISSING: '场景配置缺失',
}
const trendLabels = {
  RISING: '上升',
  STABLE: '平稳',
  FALLING: '回落',
}

const chartOption = computed(() => ({
  animation: false,
  grid: { left: 48, right: 48, top: 32, bottom: 42 },
  tooltip: { trigger: 'axis', formatter: (items) => `${items[0].axisValue}<br/>风险水位：${formatRiskScore(items[0].value)}` },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: data.value?.risk_trend?.map((item) => item.time) || [],
    axisLabel: { color: '#86909c', fontSize: 13 },
    axisLine: { lineStyle: { color: '#e5e6eb' } },
  },
  yAxis: {
    type: 'value', min: 0, max: 1,
    splitLine: { lineStyle: { color: '#e5e6eb' } },
    axisLabel: { color: '#86909c', fontSize: 13, formatter: (value) => `${Math.round(value * 100)}` },
  },
  series: [{
    type: 'line', smooth: 0.35, symbolSize: 9, showSymbol: true,
    animation: false,
    data: fullRiskScores.value,
    lineStyle: { width: 0, opacity: 0 },
    itemStyle: { color: '#1677c2', borderColor: '#fff', borderWidth: 2 },
  }, {
    type: 'line', smooth: 0.35, showSymbol: false,
    animation: false,
    data: fullRiskScores.value,
    lineStyle: { width: 4, color: '#ff7d00' },
    areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
      { offset: 0, color: 'rgba(255,125,0,.24)' }, { offset: 1, color: 'rgba(255,125,0,.02)' },
    ] } },
    markLine: {
      silent: true,
      data: [
        { yAxis: 0.4, name: '黄色关注', lineStyle: { color: '#ff7d00', type: 'dashed' } },
        { yAxis: 0.7, name: '高危干预', lineStyle: { color: '#f53f3f', type: 'dashed' } },
      ],
      label: { color: '#86909c' },
    },
  }],
}))

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getDashboard()
    animateRiskWaterLevel()
  } catch (err) {
    error.value = `无法读取首页数据：${err.message}`
  } finally {
    loading.value = false
  }
}

onMounted(load)

function metricLegacy(value, suffix = '') {
  return value === null || value === undefined ? '暂无数据' : `${value}${suffix}`
}

function metric(value, suffix = '', emptyLabel = '待采集') {
  return value === null || value === undefined || value === '' ? emptyLabel : `${value}${suffix}`
}

function onlineLabel(value) {
  if (value === true) return '设备在线'
  if (value === false) return '设备离线'
  return '设备状态未知'
}
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      class="home-page-header"
      title="今天的安全状态"
      description="风险等级来自统一状态机；页面同时呈现证据、建议和处理结果。"
    >
      <SourceBadge
        v-if="data"
        :mode="data.device?.source_mode"
        :simulated="data.device?.simulated"
      />
    </PageHeader>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <template v-if="data">
      <section v-if="data.current_risk" class="family-advice-card" aria-labelledby="family-advice-title">
        <div>
          <span class="section-kicker">给家属的建议</span>
          <h2 id="family-advice-title">{{ data.current_risk.recommended_action || '请按当前状态陪伴老人，保持联系。' }}</h2>
          <p>一次只做一个动作，先确认老人安全，再决定是否需要联系紧急联系人。</p>
          <small class="family-advice-note">建议用于家属关怀决策，不替代专业医疗判断。</small>
        </div>
      </section>
      <section v-if="data.current_risk" class="hero-risk-card" :class="`surface-${data.current_risk.risk_level.toLowerCase()}`">
        <div class="risk-score-ring" :class="`risk-ring-${riskRingTone}`" :style="{ '--risk-water-level': `${animatedRiskWaterLevel}%` }">
          <div class="risk-water" aria-hidden="true"></div>
          <span>{{ formatRiskScore(data.current_risk.risk_score) }}</span>
          <small>综合水位</small>
        </div>
        <div class="hero-risk-copy">
          <RiskBadge :level="data.current_risk.risk_level" :score="formatRiskScore(data.current_risk.risk_score)" />
          <h2>{{ data.current_risk.summary }}</h2>
          <p><strong>建议：</strong>{{ data.current_risk.recommended_action }}</p>
          <span class="last-update">更新于 {{ formatDateTime(data.current_risk.updated_at) }}</span>
        </div>
        <div class="today-status" :class="{ 'status-intervening': data.current_risk.status === 'INTERVENING' }">
          <div><span>当前事件状态</span><strong>{{ statusLabel(data.current_risk.status) }}</strong></div>
        </div>
      </section>
      <section v-else class="content-card api-empty-state">
        <el-empty description="当前暂无风险事件" />
      </section>

      <section class="metric-grid" aria-label="今日状态摘要">
        <article class="metric-card card-hover-lift">
          <span class="metric-icon mint"><Sunrise /></span>
          <div><div class="metric-label"><small>今日活动</small><el-tooltip content="今日累计活动时长，以个人基线作为参考" placement="top"><el-icon class="metric-help"><QuestionFilled /></el-icon></el-tooltip></div><strong>{{ metric(data.today.activity_minutes, ' 分钟', '暂无数据') }}</strong><span>活动以个人基线为参照</span></div>
        </article>
        <article class="metric-card card-hover-lift">
          <span class="metric-icon blue"><Connection /></span>
          <div><div class="metric-label"><small>房间活动</small><el-tooltip content="今日识别到的房间间活动次数，仅保留脱敏统计" placement="top"><el-icon class="metric-help"><QuestionFilled /></el-icon></el-tooltip></div><strong>{{ metric(data.today.room_transitions, ' 次', '暂无数据') }}</strong><span>仅保存脱敏统计</span></div>
        </article>
        <article class="metric-card card-hover-lift">
          <span class="metric-icon sand"><Monitor /></span>
          <div><div class="metric-label"><small>设备状态</small><el-tooltip content="摄像设备当前连接与采集状态" placement="top"><el-icon class="metric-help"><QuestionFilled /></el-icon></el-tooltip></div><strong>{{ onlineLabel(data.device.online) }}</strong><span>{{ displayValueLabel(data.device.name) }}</span></div>
        </article>
        <article class="metric-card card-hover-lift">
          <span class="metric-icon coral"><CircleCheck /></span>
          <div><div class="metric-label"><small>家属关怀</small><el-tooltip content="本周家属联系与关怀反馈状态" placement="top"><el-icon class="metric-help"><QuestionFilled /></el-icon></el-tooltip></div><strong>{{ metric(data.today.care_status, '', '尚未记录') }}</strong><span>本周最多主动汇总一次</span></div>
        </article>
      </section>

      <section class="dashboard-grid display-grid">
        <article class="content-card chart-card">
          <div class="card-heading">
            <div><span class="section-kicker">黄金半分钟</span><h2>风险水位与回落</h2></div>
            <el-tag type="success" effect="plain" size="large">已完成观察</el-tag>
          </div>
          <ChartPanel v-if="data.risk_trend.length" :option="chartOption" :replace="false" point-animation point-color="#1677c2" draw-animation draw-color="#ff7d00" :draw-delay="2400" height="320px" aria-label="凌晨风险水位先升高后回落的折线图" />
          <el-empty v-else description="暂无风险趋势数据" />
          <div v-if="data.risk_trend.length" class="chart-caption">
            <span
              v-for="(item, index) in data.risk_trend"
              :key="item.time"
              :style="{ left: `${data.risk_trend.length > 1 ? (index / (data.risk_trend.length - 1)) * 100 : 50}%` }"
            ><b>{{ item.time }}</b>{{ item.label }}</span>
          </div>
        </article>

        <article class="content-card device-card">
          <div class="card-heading"><div><span class="section-kicker">设备与来源</span><h2>采集链路</h2></div></div>
          <div class="device-status-line">
            <span class="online-dot" :class="{ offline: data.device.online === false, unknown: data.device.online === null }"></span>
            <div><strong>{{ onlineLabel(data.device.online) }}</strong><span>{{ data.device.collection_active ? '采集运行中' : '采集已停止' }}</span></div>
          </div>
          <dl class="detail-list">
            <div><dt>设备别名</dt><dd>{{ displayValueLabel(data.device.device_alias) }}</dd></div>
            <div><dt>适配器模式</dt><dd>{{ displayValueLabel(data.device.adapter_mode) }}</dd></div>
            <div><dt>采集状态</dt><dd>{{ data.device.collection_active ? '运行中' : '已停止' }}</dd></div>
          </dl>
          <SourceBadge :mode="data.device.source_mode" :simulated="data.device.simulated" />
        </article>
      </section>

      <div class="home-lower-grid">
      <section v-if="data.pre_fall_summary" class="content-card prefall-card">
        <div class="card-heading">
          <div><span class="section-kicker">工程风险指数 · 非概率</span><h2>个体化多源前置观察</h2></div>
          <RiskBadge :level="data.pre_fall_summary.risk_level" :score="formatRiskScore(data.pre_fall_summary.instant_risk)" />
        </div>
        <div class="prefall-status-line">
          <el-tag :type="data.pre_fall_summary.assessment_status === 'VALID' ? 'success' : 'warning'" effect="plain">
            {{ assessmentLabels[data.pre_fall_summary.assessment_status] || '兼容评估' }}
          </el-tag>
          <span>置信等级 {{ confidenceLabels[data.pre_fall_summary.confidence_level] || '未提供' }}</span>
          <span>个人基线 {{ baselineLabels[data.pre_fall_summary.baseline_status] || '未提供' }}</span>
        </div>
        <div class="prefall-grid">
          <div class="prefall-meter">
            <small>当前数秒</small>
            <strong>{{ formatRiskScore(data.pre_fall_summary.instant_risk) }}</strong>
            <span>即时失稳</span>
          </div>
          <div class="prefall-meter">
            <small>最近30秒</small>
            <strong>{{ formatRiskScore(data.pre_fall_summary.risk_30s) }}</strong>
            <span>短时累积</span>
          </div>
          <div class="prefall-meter">
            <small>最近3分钟</small>
            <strong>{{ formatRiskScore(data.pre_fall_summary.trend_3min) }}</strong>
            <span>{{ trendLabels[data.pre_fall_summary.trend_direction] || data.pre_fall_summary.trend_direction }}</span>
          </div>
          <div class="prefall-fusion">
            <dl class="detail-list compact">
              <div><dt>人体信号</dt><dd>{{ formatRiskScore(data.pre_fall_summary.human_risk) }}</dd></div>
              <div><dt>个人偏离</dt><dd>{{ formatRiskScore(data.pre_fall_summary.personal_deviation) }}</dd></div>
              <div><dt>环境风险</dt><dd>{{ formatRiskScore(data.pre_fall_summary.environment_risk) }}</dd></div>
              <div><dt>人-环境交互</dt><dd>{{ formatRiskScore(data.pre_fall_summary.interaction_risk) }}</dd></div>
            </dl>
            <div class="factor-list">
              <el-tag
                v-for="factor in data.pre_fall_summary.dominant_factors"
                :key="factor"
                effect="plain"
              >
                {{ factorLabels[factor] || factor }}
              </el-tag>
            </div>
          </div>
        </div>
        <el-alert
          v-if="data.pre_fall_summary.degradation_reasons?.length"
          :title="`降级原因：${data.pre_fall_summary.degradation_reasons.map((reason) => degradationLabels[reason] || reason).join(' · ')}`"
          type="warning"
          show-icon
          :closable="false"
        />
        <p class="intervention-line">{{ data.pre_fall_summary.recommended_intervention }}</p>
      </section>

      <section class="content-card events-card">
        <div class="card-heading">
          <div><span class="section-kicker">老人活动事件记录</span><h2>最近需要了解的事情</h2></div>
          <el-button class="timeline-link" size="large" plain @click="router.push('/events')">查看完整时间轴</el-button>
        </div>
        <div v-if="data.recent_events.length" class="event-list">
          <button
            v-for="event in data.recent_events"
            :key="event.event_id"
            class="event-row"
            type="button"
            @click="router.push(`/events/${event.event_id}`)"
          >
            <span class="event-time">{{ formatDateTime(event.created_at) }}</span>
            <span class="event-main"><b>{{ event.title }}</b><small>{{ domainLabel(event.primary_domain) }} · {{ statusLabel(event.status) }}</small></span>
            <RiskBadge :level="event.risk_level" compact />
            <SourceBadge :mode="event.source_mode" :simulated="event.simulated" />
            <span class="row-arrow" aria-hidden="true">→</span>
          </button>
        </div>
        <el-empty v-else description="暂无最近事件" />
      </section>
      </div>
    </template>
  </div>
</template>
