<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CircleCheckFilled, Connection, Monitor, Sunrise } from '@element-plus/icons-vue'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ChartPanel from '../components/common/ChartPanel.vue'
import { getDashboard } from '../services/repository'
import { domainLabel, formatDateTime, formatRiskScore, statusLabel } from '../utils/format'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const data = ref(null)
const factorLabels = {
  fall_precursor_evidence: '跌倒前兆证据',
  personal_baseline_deviation: '偏离个人基线',
  environment_interaction_risk: '人-环境交互风险',
  data_quality_downgrade: '数据质量降级',
  multi_scale_accumulation: '多时标累积',
  normal_fluctuation: '日常波动',
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
      <section class="hero-risk-card" :class="`surface-${data.current_risk.risk_level.toLowerCase()}`">
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

      <section class="metric-grid" aria-label="今日状态摘要">
        <article class="metric-card">
          <span class="metric-icon mint"><Sunrise /></span>
          <div><small>今日活动</small><strong>{{ data.today.activity_minutes }} 分钟</strong><span>活动以个人基线为参照</span></div>
        </article>
        <article class="metric-card">
          <span class="metric-icon blue"><Connection /></span>
          <div><small>房间活动</small><strong>{{ data.today.room_transitions }} 次</strong><span>仅保存脱敏统计</span></div>
        </article>
        <article class="metric-card">
          <span class="metric-icon sand"><Monitor /></span>
          <div><small>设备状态</small><strong>{{ data.device.online ? '在线' : '离线' }}</strong><span>{{ data.device.name }}</span></div>
        </article>
        <article class="metric-card">
          <span class="metric-icon coral"><CircleCheckFilled /></span>
          <div><small>家属关怀</small><strong>{{ data.today.care_status }}</strong><span>本周最多主动汇总一次</span></div>
        </article>
      </section>

      <section class="dashboard-grid">
        <article class="content-card chart-card">
          <div class="card-heading">
            <div><span class="section-kicker">黄金半分钟</span><h2>风险水位与回落</h2></div>
            <el-tag type="success" effect="plain" size="large">已完成观察</el-tag>
          </div>
          <ChartPanel :option="chartOption" height="320px" aria-label="凌晨风险水位先升高后回落的折线图" />
          <div class="chart-caption">
            <span v-for="item in data.risk_trend" :key="item.time"><b>{{ item.time }}</b>{{ item.label }}</span>
          </div>
        </article>

        <article class="content-card device-card">
          <div class="card-heading"><div><span class="section-kicker">设备与来源</span><h2>采集链路</h2></div></div>
          <div class="device-status-line">
            <span class="online-dot" :class="{ offline: !data.device.online }"></span>
            <div><strong>{{ data.device.online ? '设备在线' : '设备离线' }}</strong><span>最后更新 {{ formatDateTime(data.device.last_seen) }}</span></div>
          </div>
          <dl class="detail-list">
            <div><dt>设备</dt><dd>{{ data.device.name }}</dd></div>
            <div><dt>适配器</dt><dd>{{ data.device.adapter }}</dd></div>
            <div><dt>数据质量</dt><dd>{{ Math.round(data.device.data_quality * 100) }}%</dd></div>
          </dl>
          <SourceBadge :mode="data.device.source_mode" :simulated="data.device.simulated" />
          <p class="privacy-note">前端仅读取后端状态和授权片段，不保存设备账号或 AccessToken。</p>
        </article>
      </section>

      <section v-if="data.pre_fall_summary" class="content-card prefall-card">
        <div class="card-heading">
          <div><span class="section-kicker">跌倒前兆</span><h2>个体记忆驱动的多时间尺度预警</h2></div>
          <RiskBadge :level="data.pre_fall_summary.risk_level" />
        </div>
        <div class="prefall-grid">
          <div class="prefall-meter">
            <small>当前数秒</small>
            <strong>{{ formatRiskScore(data.pre_fall_summary.instant_risk) }}</strong>
            <span>即时失稳</span>
          </div>
          <div class="prefall-meter">
            <small>未来30秒</small>
            <strong>{{ formatRiskScore(data.pre_fall_summary.risk_30s) }}</strong>
            <span>短时恶化</span>
          </div>
          <div class="prefall-meter">
            <small>最近3分钟</small>
            <strong>{{ formatRiskScore(data.pre_fall_summary.trend_3min) }}</strong>
            <span>{{ trendLabels[data.pre_fall_summary.trend_direction] || data.pre_fall_summary.trend_direction }}</span>
          </div>
          <div class="prefall-fusion">
            <dl class="detail-list compact">
              <div><dt>个人偏离</dt><dd>{{ formatRiskScore(data.pre_fall_summary.personal_deviation) }}</dd></div>
              <div><dt>环境交互</dt><dd>{{ formatRiskScore(data.pre_fall_summary.environment_risk) }}</dd></div>
              <div><dt>质量降级</dt><dd>{{ formatRiskScore(data.pre_fall_summary.quality_penalty) }}</dd></div>
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
        <p class="intervention-line">{{ data.pre_fall_summary.recommended_intervention }}</p>
      </section>

      <section class="content-card events-card">
        <div class="card-heading">
          <div><span class="section-kicker">统一事件时间轴</span><h2>最近需要了解的事情</h2></div>
          <el-button size="large" plain @click="router.push('/events')">查看完整时间轴</el-button>
        </div>
        <div class="event-list">
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
      </section>
    </template>
  </div>
</template>
