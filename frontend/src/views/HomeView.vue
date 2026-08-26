<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CircleCheckFilled, Connection, Monitor, Sunrise } from '@element-plus/icons-vue'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ChartPanel from '../components/common/ChartPanel.vue'
import TechnicalDisclosure from '../components/common/TechnicalDisclosure.vue'
import { getDashboard } from '../services/repository'
import { domainLabel, formatDateTime, formatPercent, formatRiskScore, statusLabel } from '../utils/format'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const data = ref(null)
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
  grid: { left: 46, right: 24, top: 32, bottom: 42 },
  tooltip: { trigger: 'axis', formatter: (items) => `${items[0].axisValue}<br/>风险水位：${formatRiskScore(items[0].value)}` },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: data.value?.risk_trend?.map((item) => item.time) || [],
    axisLabel: { color: '#64736f', fontSize: 13 },
    axisLine: { lineStyle: { color: '#dce8e4' } },
  },
  yAxis: {
    type: 'value', min: 0, max: 1,
    splitLine: { lineStyle: { color: '#edf3f1' } },
    axisLabel: { color: '#64736f', fontSize: 13, formatter: (value) => `${Math.round(value * 100)}` },
  },
  series: [{
    type: 'line', smooth: 0.35, symbolSize: 9,
    data: data.value?.risk_trend?.map((item) => item.score) || [],
    lineStyle: { width: 4, color: '#e58b3a' },
    itemStyle: { color: '#176b65', borderColor: '#fff', borderWidth: 2 },
    areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
      { offset: 0, color: 'rgba(229,139,58,.28)' }, { offset: 1, color: 'rgba(229,139,58,.02)' },
    ] } },
    markLine: {
      silent: true,
      data: [
        { yAxis: 0.4, name: '黄色关注', lineStyle: { color: '#d6a63b', type: 'dashed' } },
        { yAxis: 0.7, name: '橙色干预', lineStyle: { color: '#dd6b20', type: 'dashed' } },
      ],
      label: { color: '#64736f' },
    },
  }],
}))

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getDashboard()
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
      title="今天的安全状态，一眼看清"
      description="风险等级来自统一状态机；页面同时呈现证据、建议和处理结果。"
    >
      <SourceBadge
        v-if="data"
        :mode="data.device?.source_mode"
        :simulated="data.device?.simulated"
        :show-description="true"
      />
    </PageHeader>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <template v-if="data">
      <section v-if="data.current_risk" class="hero-risk-card" :class="`surface-${data.current_risk.risk_level.toLowerCase()}`">
        <div class="risk-score-ring">
          <span>{{ formatRiskScore(data.current_risk.risk_score) }}</span>
          <small>综合水位</small>
        </div>
        <div class="hero-risk-copy">
          <RiskBadge :level="data.current_risk.risk_level" />
          <h2>{{ data.current_risk.summary }}</h2>
          <p><strong>建议：</strong>{{ data.current_risk.recommended_action }}</p>
          <span class="last-update">更新于 {{ formatDateTime(data.current_risk.updated_at) }}</span>
        </div>
        <div class="today-status">
          <el-icon><CircleCheckFilled /></el-icon>
          <div><strong>{{ statusLabel(data.current_risk.status) }}</strong><span>当前事件状态</span></div>
        </div>
      </section>
      <section v-else class="content-card api-empty-state">
        <el-empty description="后端当前没有该居民的风险事件" />
        <p>页面保持 API 数据源，不使用固定 Mock 风险水位填充。</p>
      </section>

      <section class="metric-grid" aria-label="今日状态摘要">
        <article class="metric-card">
          <span class="metric-icon mint"><Sunrise /></span>
          <div><small>今日活动</small><strong>{{ metric(data.today.activity_minutes, ' 分钟', '暂无数据') }}</strong><span>活动以个人基线为参照</span></div>
        </article>
        <article class="metric-card">
          <span class="metric-icon blue"><Connection /></span>
          <div><small>房间活动</small><strong>{{ metric(data.today.room_transitions, ' 次', '暂无数据') }}</strong><span>仅保存脱敏统计</span></div>
        </article>
        <article class="metric-card">
          <span class="metric-icon sand"><Monitor /></span>
          <div><small>设备状态</small><strong>{{ onlineLabel(data.device.online) }}</strong><span>{{ data.device.name }}</span></div>
        </article>
        <article class="metric-card">
          <span class="metric-icon coral"><CircleCheckFilled /></span>
          <div><small>家属关怀</small><strong>{{ metric(data.today.care_status, '', '尚未记录') }}</strong><span>本周最多主动汇总一次</span></div>
        </article>
      </section>

      <TechnicalDisclosure title="趋势与设备详情" summary="风险趋势、设备状态和多时标工程指数">
      <section class="dashboard-grid">
        <article class="content-card chart-card">
          <div class="card-heading">
            <div><span class="section-kicker">黄金半分钟</span><h2>风险水位与回落</h2></div>
            <el-tag type="success" effect="plain" size="large">已完成观察</el-tag>
          </div>
          <ChartPanel v-if="data.risk_trend.length" :option="chartOption" height="320px" aria-label="凌晨风险水位先升高后回落的折线图" />
          <el-empty v-else description="后端未提供逐点风险趋势，事件状态以时间轴为准" />
          <div v-if="data.risk_trend.length" class="chart-caption">
            <span v-for="item in data.risk_trend" :key="item.time"><b>{{ item.time }}</b>{{ item.label }}</span>
          </div>
        </article>

        <article class="content-card device-card">
          <div class="card-heading"><div><span class="section-kicker">设备与来源</span><h2>采集链路</h2></div></div>
          <div class="device-status-line">
            <span class="online-dot" :class="{ offline: data.device.online === false, unknown: data.device.online === null }"></span>
            <div><strong>{{ onlineLabel(data.device.online) }}</strong><span>{{ data.device.collection_active ? '采集运行中' : '采集已停止' }}</span></div>
          </div>
          <dl class="detail-list">
            <div><dt>设备别名</dt><dd>{{ data.device.device_alias }}</dd></div>
            <div><dt>适配器模式</dt><dd>{{ data.device.adapter_mode }}</dd></div>
            <div><dt>采集状态</dt><dd>{{ data.device.collection_active ? '运行中' : '已停止' }}</dd></div>
          </dl>
          <SourceBadge :mode="data.device.source_mode" :simulated="data.device.simulated" />
          <p class="privacy-note">前端仅展示文档约定的设备状态和事件数据。</p>
        </article>
      </section>

      <section v-if="data.pre_fall_summary" class="content-card prefall-card">
        <div class="card-heading">
          <div><span class="section-kicker">工程风险指数 · 非概率</span><h2>个体化多源前置观察</h2></div>
          <RiskBadge :level="data.pre_fall_summary.risk_level" />
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
      </TechnicalDisclosure>

      <section class="content-card events-card">
        <div class="card-heading">
          <div><span class="section-kicker">统一事件时间轴</span><h2>最近需要了解的事情</h2></div>
          <el-button size="large" plain @click="router.push('/events')">查看完整时间轴</el-button>
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
        <el-empty v-else description="当前 API 中没有最近事件" />
      </section>
    </template>
  </div>
</template>
