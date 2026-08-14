<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ChartPanel from '../components/common/ChartPanel.vue'
import { DELIVERY_STATUSES } from '../domain/constants'
import { getEvent, runtime, submitInterventionResult } from '../services/repository'
import { domainLabel, formatDateTime, formatPercent, formatRiskScore, statusLabel } from '../utils/format'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const event = ref(null)
const traceOpen = ref(false)
const selectedEvidence = ref(null)
const syncState = ref('loading')
const syncWarning = ref('')
const submittingResidentResponse = ref(false)
const residentResponseRecorded = ref(false)

const POLL_INTERVAL_MS = 1500
const TERMINAL_STATUSES = new Set(['RESOLVED', 'ESCALATED'])
let pollTimer = null
let sessionId = 0

const syncLabel = computed(() => ({
  loading: '正在读取事件',
  polling: '自动同步中',
  retrying: '同步重试中',
  complete: '同步已完成',
  idle: runtime.mode === 'mock' ? '固定数据模式' : '等待同步',
}[syncState.value]))

const syncTagType = computed(() => ({
  retrying: 'warning',
  complete: 'success',
  idle: 'info',
}[syncState.value] || 'primary'))

const selectedObservations = computed(() => {
  const ids = new Set(selectedEvidence.value?.observation_ids || [])
  return (event.value?.observations || []).filter((observation) => ids.has(observation.observation_id))
})

const displayEvidences = computed(() => {
  const detailsById = new Map((event.value?.evidences || []).map((evidence) => [evidence.evidence_id, evidence]))
  return (event.value?.evidence_summary || []).map((summary) => ({
    ...summary,
    ...(detailsById.get(summary.evidence_id) || {}),
  }))
})

const riskChartOption = computed(() => ({
  grid: { left: 42, right: 20, top: 28, bottom: 36 },
  tooltip: { trigger: 'axis', valueFormatter: (value) => `${formatRiskScore(value)}` },
  xAxis: { type: 'category', boundaryGap: false, data: event.value?.risk_history?.map((item) => item.time) || [], axisLabel: { color: '#64736f' } },
  yAxis: { type: 'value', min: 0, max: 1, splitLine: { lineStyle: { color: '#edf3f1' } }, axisLabel: { color: '#64736f', formatter: (value) => `${Math.round(value * 100)}` } },
  series: [{
    type: 'line', smooth: true, symbolSize: 8,
    data: event.value?.risk_history?.map((item) => item.score) || [],
    lineStyle: { width: 4, color: '#df7d32' }, itemStyle: { color: '#176b65' },
    areaStyle: { color: 'rgba(223,125,50,.12)' },
  }],
}))

const displayRuleTraces = computed(() => event.value?.rule_traces || [])

function contextText(trace) {
  const entries = Object.entries(trace?.context_snapshot?.contributions || {}).filter(([, value]) => Number(value) > 0)
  return entries.length ? entries.map(([key, value]) => `${key} +${value}`).join(' · ') : '无附加上下文'
}

function traceScore(trace) {
  const value = trace?.score_components?.final_score
  return typeof value === 'number' ? formatRiskScore(value) : '未生成事件分数'
}

function qualityText(trace) {
  const items = trace?.quality_snapshot?.evidences || []
  if (!items.length) return '无证据质量快照'
  return items.map((item) => (
    `${item.evidence_type}: 质量${item.data_quality} / 置信${item.confidence} / ${item.usable ? '通过' : '拦截'}`
  )).join('；')
}

function baselineStatusText(trace) {
  const status = trace?.baseline_snapshot?.overall_status || 'INSUFFICIENT'
  return { PROVISIONAL: '初步基线', INSUFFICIENT: '样本不足', STABLE: '工程稳定基线（非医学）' }[status] || status
}

function scoreComponentsText(trace) {
  const score = trace?.score_components || {}
  if (typeof score.final_score !== 'number') return '本次规则不生成事件分数'
  return `严重度${score.severity}、置信度${score.confidence}、质量${score.data_quality}、上下文${score.context}`
}

function openTrace(evidence) {
  selectedEvidence.value = evidence
  traceOpen.value = true
}

function clearPollTimer() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function pollingEnabled() {
  return runtime.mode !== 'mock'
}

function isTerminal(currentEvent) {
  return TERMINAL_STATUSES.has(currentEvent?.status)
}

function schedulePoll(activeSession) {
  clearPollTimer()
  if (activeSession !== sessionId || !pollingEnabled() || isTerminal(event.value)) return
  pollTimer = window.setTimeout(() => {
    pollTimer = null
    void refreshEvent(activeSession)
  }, POLL_INTERVAL_MS)
}

async function refreshEvent(activeSession, initial = false) {
  if (activeSession !== sessionId) return
  if (initial) loading.value = true
  else syncState.value = 'polling'

  try {
    const nextEvent = await getEvent(route.params.eventId || 'event-fall-100')
    if (activeSession !== sessionId) return
    event.value = nextEvent
    error.value = ''
    syncWarning.value = ''
    if (isTerminal(nextEvent)) {
      syncState.value = 'complete'
      clearPollTimer()
    } else if (pollingEnabled()) {
      syncState.value = 'polling'
      schedulePoll(activeSession)
    } else {
      syncState.value = 'idle'
    }
  } catch (err) {
    if (activeSession !== sessionId) return
    if (event.value) syncWarning.value = `自动同步暂时失败，将继续重试：${err.message}`
    else error.value = `无法读取事件：${err.message}`
    syncState.value = pollingEnabled() ? 'retrying' : 'idle'
    if (pollingEnabled()) schedulePoll(activeSession)
  } finally {
    if (activeSession === sessionId && initial) loading.value = false
  }
}

function startEventSession() {
  sessionId += 1
  const activeSession = sessionId
  clearPollTimer()
  event.value = null
  error.value = ''
  syncWarning.value = ''
  syncState.value = 'loading'
  traceOpen.value = false
  selectedEvidence.value = null
  submittingResidentResponse.value = false
  residentResponseRecorded.value = false
  void refreshEvent(activeSession, true)
}

function stopEventSession() {
  sessionId += 1
  clearPollTimer()
}

async function confirmResidentStable() {
  if (!event.value || submittingResidentResponse.value || residentResponseRecorded.value) return
  submittingResidentResponse.value = true
  try {
    const result = await submitInterventionResult(event.value, 'stable')
    const interventions = event.value.interventions || (event.value.interventions = [])
    const existingIndex = interventions.findIndex((item) => item.result_id === result.result_id)
    if (existingIndex >= 0) interventions.splice(existingIndex, 1, result)
    else interventions.push(result)
    residentResponseRecorded.value = true
    ElMessage.success('坐稳确认已记录，系统将继续观察风险是否回落')
  } catch (err) {
    ElMessage.error(`确认提交失败：${err.message}`)
  } finally {
    submittingResidentResponse.value = false
  }
}

watch(() => [route.params.eventId, runtime.mode], startEventSession, { immediate: true })
onBeforeUnmount(stopEventSession)
</script>

<template>
  <div v-loading="loading" data-testid="event-detail-view">
    <PageHeader
      title="风险事件详情"
      description="从证据形成、系统动作到观察回落，每一步都有记录。"
    >
      <el-tag :type="syncTagType" size="large" effect="plain" data-testid="event-sync-status">{{ syncLabel }}</el-tag>
      <el-button size="large" plain @click="router.back()">返回</el-button>
    </PageHeader>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-alert v-if="syncWarning" :title="syncWarning" type="warning" show-icon :closable="false" />

    <template v-if="event">
      <section class="event-summary-card">
        <div class="event-summary-main">
          <div class="summary-badges">
            <RiskBadge :level="event.risk_level" />
            <el-tag size="large" effect="plain">{{ statusLabel(event.status) }}</el-tag>
            <SourceBadge :mode="event.source_mode" :simulated="event.simulated" />
          </div>
          <h2>{{ event.title }}</h2>
          <p>{{ event.recommended_action }}</p>
          <div class="meta-line">
            <span>事件 {{ event.event_id }}</span><span>{{ domainLabel(event.primary_domain) }}</span><span>{{ event.ruleset_version }}</span><span>{{ formatDateTime(event.created_at) }}</span>
          </div>
        </div>
        <div class="event-score"><span>{{ formatRiskScore(event.risk_score) }}</span><small>事件峰值</small></div>
      </section>

      <section class="event-detail-grid">
        <div class="event-primary-column">
          <article class="content-card">
            <div class="card-heading"><div><span class="section-kicker">Evidence</span><h2>为什么系统建议关注</h2></div><span>{{ event.evidence_summary.length }} 条证据</span></div>
            <div v-if="displayEvidences.length" class="evidence-grid">
              <article v-for="evidence in displayEvidences" :key="evidence.evidence_id" class="evidence-card">
                <div class="evidence-top"><code>{{ evidence.evidence_type }}</code><span>{{ evidence.time_scale || '摘要' }}</span></div>
                <h3>{{ evidence.explanation }}</h3>
                <div class="evidence-metrics">
                  <span><small>异常程度</small><b>{{ formatPercent(evidence.severity) }}</b></span>
                  <span><small>置信度</small><b>{{ formatPercent(evidence.confidence) }}</b></span>
                  <span><small>数据质量</small><b>{{ formatPercent(evidence.data_quality) }}</b></span>
                </div>
                <div class="evidence-trace-summary">
                  <span>{{ (evidence.observation_ids || []).length }} 条 Observation</span>
                  <span>{{ evidence.adapter_version || '暂无适配器详情' }}</span>
                </div>
                <SourceBadge v-if="evidence.source_mode" :mode="evidence.source_mode" :simulated="evidence.simulated" />
                <el-button v-if="evidence.observation_ids?.length" class="trace-button" size="large" plain @click="openTrace(evidence)">查看原始观测</el-button>
              </article>
            </div>
            <el-empty v-else description="该绿色事件没有异常 Evidence" />
          </article>

          <article v-if="displayRuleTraces.length" class="content-card" data-testid="rule-trace-panel">
            <div class="card-heading"><div><span class="section-kicker">RuleTrace</span><h2>后端实际规则判断</h2></div><span>{{ displayRuleTraces.length }} 次评估</span></div>
            <div class="tool-results">
              <article v-for="trace in displayRuleTraces" :key="trace.trace_id">
                <el-tag effect="dark">{{ trace.matched_rule }}</el-tag>
                <h3>{{ trace.reason || '后端未返回规则解释' }}</h3>
                <dl class="detail-list">
                  <div><dt>状态迁移</dt><dd>{{ trace.previous_status || trace.previous_state }} → {{ trace.next_status || trace.next_state }}</dd></div>
                  <div><dt>实际评分</dt><dd>{{ traceScore(trace) }}</dd></div>
                  <div><dt>评分分量</dt><dd>{{ scoreComponentsText(trace) }}</dd></div>
                  <div><dt>质量门槛</dt><dd>{{ trace.thresholds?.data_quality ?? '—' }}</dd></div>
                  <div><dt>逐条质量</dt><dd>{{ qualityText(trace) }}</dd></div>
                  <div><dt>基线状态</dt><dd>{{ baselineStatusText(trace) }}</dd></div>
                  <div><dt>上下文</dt><dd>{{ contextText(trace) }}</dd></div>
                  <div><dt>查询窗口</dt><dd>短时 {{ trace.queried_windows?.short_seconds ?? '—' }}秒 · 中期 {{ trace.queried_windows?.medium_hours ?? '—' }}小时 · 长期 {{ trace.queried_windows?.long_days ?? '—' }}天</dd></div>
                </dl>
              </article>
            </div>
          </article>

          <article class="content-card">
            <div class="card-heading"><div><span class="section-kicker">系统动作</span><h2>干预与观察时间轴</h2></div></div>
            <el-timeline v-if="event.timeline?.length" class="action-timeline" data-testid="event-action-timeline">
              <el-timeline-item v-for="item in event.timeline" :key="`${item.time}-${item.title}`" :timestamp="item.time" placement="top">
                <div class="timeline-card"><strong>{{ item.title }}</strong><p>{{ item.detail }}</p><el-tag effect="plain">{{ item.status }}</el-tag></div>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else description="当前事件暂无系统动作时间轴" />
          </article>

          <article v-if="event.risk_history?.length" class="content-card">
            <div class="card-heading"><div><span class="section-kicker">风险趋势</span><h2>{{ event.status === 'RESOLVED' ? '风险水位已经回落' : '当前仍在干预或观察' }}</h2></div><el-tag :type="event.status === 'RESOLVED' ? 'success' : 'warning'" size="large">{{ event.observation_seconds || 0 }} 秒观察</el-tag></div>
            <ChartPanel :option="riskChartOption" height="270px" aria-label="风险事件发生后逐步回落的趋势图" />
          </article>
          <article v-else-if="event.rule_traces?.length" class="content-card api-empty-state">
            <div class="card-heading"><div><span class="section-kicker">风险趋势</span><h2>以真实状态迁移为准</h2></div></div>
            <el-alert title="后端未返回逐点风险分，页面不会根据状态猜测数值；请查看上方规则与动作时间轴。" type="info" show-icon :closable="false" />
          </article>
        </div>

        <aside class="event-aside">
          <section class="content-card tool-card">
            <div class="card-heading"><div><span class="section-kicker">工具结果</span><h2>执行记录</h2></div></div>
            <div v-if="event.interventions?.length" class="tool-results">
              <article v-for="result in event.interventions" :key="result.result_id">
                <el-tag :type="DELIVERY_STATUSES[result.delivery_status]?.type || 'info'" size="large" effect="dark">
                  {{ DELIVERY_STATUSES[result.delivery_status]?.label || result.delivery_status }}
                </el-tag>
                <h3>{{ result.tool_name }}</h3>
                <dl class="detail-list">
                  <div><dt>执行方式</dt><dd>{{ result.action_type }}</dd></div>
                  <div><dt>老人反馈</dt><dd>{{ result.resident_response || '暂无' }}</dd></div>
                  <div v-if="result.family_feedback"><dt>家属反馈</dt><dd>{{ result.family_feedback }}</dd></div>
                  <div><dt>干预后水位</dt><dd>{{ formatRiskScore(result.risk_after) }}</dd></div>
                  <div><dt>结果</dt><dd>{{ result.resolution_reason || '等待结果' }}</dd></div>
                </dl>
                <el-alert v-if="result.delivery_status === 'FAILED'" title="工具调用失败已如实保留，未标记为干预成功。" type="error" show-icon :closable="false" />
              </article>
            </div>
            <el-empty v-else description="该事件没有调用工具" />
          </section>

          <section v-if="event.primary_domain === 'FALL' && event.status !== 'RESOLVED'" class="elder-action-card" data-testid="elder-single-action">
            <span>老人侧柔性提醒</span>
            <h2>先坐稳，扶住身边固定物</h2>
            <p>一次只提供一个清楚动作，不制造紧张。</p>
            <el-button
              data-testid="elder-stable-submit"
              type="primary"
              size="large"
              :loading="submittingResidentResponse"
              :disabled="residentResponseRecorded"
              @click="confirmResidentStable"
            >
              {{ residentResponseRecorded ? '坐稳确认已记录' : '我已坐稳' }}
            </el-button>
            <p v-if="residentResponseRecorded" class="elder-action-note">确认不会直接关闭事件，仍由后端 Evidence 和观察期决定风险是否回落。</p>
          </section>
        </aside>
      </section>

      <el-drawer v-model="traceOpen" title="Evidence 原始来源" size="520px">
        <div v-if="selectedEvidence" class="trace-drawer" data-testid="evidence-trace">
          <SourceBadge :mode="selectedEvidence.source_mode" :simulated="selectedEvidence.simulated" />
          <h2>{{ selectedEvidence.evidence_type }}</h2>
          <p>{{ selectedEvidence.explanation }}</p>
          <dl class="detail-list">
            <div><dt>Evidence ID</dt><dd>{{ selectedEvidence.evidence_id }}</dd></div>
            <div><dt>风险方向</dt><dd>{{ domainLabel(selectedEvidence.risk_domain) }}</dd></div>
            <div><dt>生成时间</dt><dd>{{ formatDateTime(selectedEvidence.timestamp) }}</dd></div>
            <div><dt>适配器版本</dt><dd>{{ selectedEvidence.adapter_version }}</dd></div>
            <div><dt>个人基线</dt><dd>{{ selectedEvidence.baseline_value ?? '—' }}</dd></div>
            <div><dt>当前值</dt><dd>{{ selectedEvidence.current_value ?? '—' }}</dd></div>
            <div><dt>基线偏离</dt><dd>{{ selectedEvidence.baseline_deviation ?? '—' }}</dd></div>
          </dl>
          <h3>关联 Observation</h3>
          <article v-for="observation in selectedObservations" :key="observation.observation_id" class="observation-card">
            <strong>{{ observation.feature_name }}</strong>
            <code>{{ observation.observation_id }}</code>
            <p>{{ observation.feature_value }} {{ observation.unit || '' }} · {{ formatDateTime(observation.timestamp) }}</p>
            <dl class="detail-list compact-list">
              <div><dt>来源</dt><dd>{{ observation.source }}</dd></div>
              <div><dt>置信度</dt><dd>{{ formatPercent(observation.confidence) }}</dd></div>
              <div><dt>质量</dt><dd>{{ formatPercent(observation.data_quality) }}</dd></div>
            </dl>
          </article>
          <el-alert v-if="!selectedObservations.length" title="接口尚未返回关联 Observation，当前只能追溯到 Evidence ID。" type="warning" show-icon :closable="false" />
        </div>
      </el-drawer>
    </template>
  </div>
</template>
