<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { WarningFilled } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../components/common/PageHeader.vue'
import MediaPanel from '../components/common/MediaPanel.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ChartPanel from '../components/common/ChartPanel.vue'
import TechnicalDisclosure from '../components/common/TechnicalDisclosure.vue'
import { DELIVERY_STATUSES } from '../domain/constants'
import { getAsset, getEvent, getEventExplanation, interveneEvent, runtime, submitInterventionResult } from '../services/repository'
import { resolveEventAssetId } from '../services/viewModel'
import { displayValueLabel, domainLabel, evidenceTypeLabel, formatAssetId, formatDateTime, formatPercent, formatRiskScore, statusLabel, timeScaleLabel, unitLabel } from '../utils/format'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const event = ref(null)
const traceOpen = ref(false)
const selectedEvidence = ref(null)
const asset = ref(null)
const assetId = ref(null)
const assetState = ref('idle')
const assetMessage = ref('')
const syncState = ref('loading')
const syncWarning = ref('')
const submittingResidentResponse = ref(false)
const residentResponseRecorded = ref(false)
const explanation = ref(null)
const explanationError = ref('')
const explanationState = ref('loading')
const submittingIntervention = ref(false)
const interventionRequested = ref(false)
const forewarningSnapshots = ref([])
const highRiskDialogVisible = ref(false)
const highRiskAcknowledged = ref(false)

const POLL_INTERVAL_MS = 1500
const TERMINAL_STATUSES = new Set(['RESOLVED', 'ESCALATED', 'FALSE_ALARM'])
const EXPLANATION_TERMINAL_STATUSES = new Set(['SUCCESS', 'FALLBACK', 'FAILED'])
const EXPLANATION_STATUS_META = Object.freeze({
  NOT_REQUESTED: { label: '暂无智能体解释', type: 'info' },
  PENDING: { label: '解释生成中', type: 'info' },
  PROCESSING: { label: '解释生成中', type: 'info' },
  RETRY: { label: '解释生成重试中', type: 'warning' },
  SUCCESS: { label: '智能体解释', type: 'success' },
  FALLBACK: { label: '模板降级解释', type: 'warning' },
  FAILED: { label: '解释生成失败', type: 'danger' },
})
let pollTimer = null
let explanationPollTimer = null
let sessionId = 0

const syncLabel = computed(() => ({
  loading: '正在读取事件',
  polling: '自动同步中',
  retrying: '同步重试中',
  complete: '同步已完成',
  idle: runtime.mode === 'replay' ? '离线授权回放' : '等待同步',
}[syncState.value]))

const syncTagType = computed(() => ({
  retrying: 'warning',
  complete: 'success',
  idle: 'info',
}[syncState.value] || 'primary'))

const explanationStatusMeta = computed(() => (
  EXPLANATION_STATUS_META[explanation.value?.status] || { label: '解释生成中', type: 'info' }
))

const explanationGeneratedBy = computed(() => (
  explanation.value?.explanation?.generated_by || '未提供'
))

const explanationFallbackUsed = computed(() => (
  explanation.value?.explanation?.fallback_used === true
))

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
  xAxis: { type: 'category', boundaryGap: false, data: event.value?.risk_history?.map((item) => item.time) || [], axisLabel: { color: '#86909c' } },
  yAxis: { type: 'value', min: 0, max: 1, splitLine: { lineStyle: { color: '#e5e6eb' } }, axisLabel: { color: '#86909c', formatter: (value) => `${Math.round(value * 100)}` } },
  series: [{
    type: 'line', smooth: true, symbolSize: 8,
    data: event.value?.risk_history?.map((item) => item.score) || [],
    lineStyle: { width: 4, color: '#ff7d00' }, itemStyle: { color: '#1677c2' },
    areaStyle: { color: 'rgba(255,125,0,.12)' },
  }],
}))

const displayRuleTraces = computed(() => event.value?.rule_traces || [])
const hasPrimaryDetailContent = computed(() => Boolean(
  displayEvidences.value.length
  || displayRuleTraces.value.length
  || event.value?.timeline?.length
  || event.value?.risk_history?.length
))
const hasAsideDetailContent = computed(() => Boolean(
  event.value
  && (
    ['OPEN', 'INTERVENING'].includes(event.value.status)
    || event.value.interventions?.length
    || (event.value.primary_domain === 'FALL' && event.value.status !== 'RESOLVED')
  )
))
const hasDetailGridContent = computed(() => hasPrimaryDetailContent.value || hasAsideDetailContent.value)
const preInterventionSnapshot = computed(() => (
  forewarningSnapshots.value.find((item) => item.phase === 'PRE_INTERVENTION') || forewarningSnapshots.value[0] || null
))
const postInterventionSnapshot = computed(() => (
  [...forewarningSnapshots.value].reverse().find((item) => item.phase === 'POST_INTERVENTION') || null
))
const forewarningDelta = computed(() => {
  if (!preInterventionSnapshot.value || !postInterventionSnapshot.value) return null
  return postInterventionSnapshot.value.instant.engineering_index - preInterventionSnapshot.value.instant.engineering_index
})

function assessmentLabel(value) {
  return { VALID: '完整评估', PARTIAL: '降级评估', INSUFFICIENT: '数据不足' }[value] || value
}

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

function playHighRiskTone() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext
    if (!AudioContext) return
    const context = new AudioContext()
    ;[0, 0.45, 0.9].forEach((offset) => {
      const oscillator = context.createOscillator()
      const gain = context.createGain()
      oscillator.type = 'sine'
      oscillator.frequency.value = 740
      gain.gain.setValueAtTime(0.0001, context.currentTime + offset)
      gain.gain.exponentialRampToValueAtTime(0.16, context.currentTime + offset + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + offset + 0.2)
      oscillator.connect(gain).connect(context.destination)
      oscillator.start(context.currentTime + offset)
      oscillator.stop(context.currentTime + offset + 0.22)
    })
    window.setTimeout(() => context.close(), 1500)
  } catch { /* 浏览器未授权声音时不影响告警展示 */ }
}

function acknowledgeHighRisk() {
  highRiskDialogVisible.value = false
  highRiskAcknowledged.value = true
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

function clearExplanationPollTimer() {
  if (explanationPollTimer !== null) {
    window.clearTimeout(explanationPollTimer)
    explanationPollTimer = null
  }
}

async function syncAsset(currentEvent, activeSession) {
  const nextAssetId = resolveEventAssetId(currentEvent)
  if (!nextAssetId) {
    asset.value = null
    assetId.value = null
    assetState.value = 'idle'
    assetMessage.value = ''
    return
  }
  if (assetId.value === nextAssetId && assetState.value !== 'idle') return

  asset.value = null
  assetId.value = nextAssetId
  assetState.value = 'loading'
  assetMessage.value = ''
  try {
    const result = await getAsset(nextAssetId)
    if (activeSession !== sessionId || assetId.value !== nextAssetId) return
    asset.value = result
    assetState.value = 'ready'
  } catch (err) {
    if (activeSession !== sessionId || assetId.value !== nextAssetId) return
    asset.value = null
    const missing = err?.response?.status === 404 || err?.api?.code === 'ASSET_NOT_FOUND'
    assetState.value = missing ? 'missing' : 'failed'
    assetMessage.value = missing
      ? `后端暂无素材记录（${nextAssetId}）`
      : `素材读取失败（${nextAssetId}）：${err.message}`
  }
}

function pollingEnabled() {
  return runtime.mode !== 'replay'
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

function scheduleExplanationPoll(activeSession) {
  clearExplanationPollTimer()
  if (activeSession !== sessionId || EXPLANATION_TERMINAL_STATUSES.has(explanation.value?.status)) return
  explanationPollTimer = window.setTimeout(() => {
    explanationPollTimer = null
    void refreshExplanation(activeSession)
  }, POLL_INTERVAL_MS)
}

async function refreshExplanation(activeSession, initial = false) {
  if (activeSession !== sessionId) return
  if (initial) explanationState.value = 'loading'
  try {
    const result = await getEventExplanation(route.params.eventId || 'event-fall-100')
    if (activeSession !== sessionId) return
    explanation.value = result
    explanationError.value = ''
    explanationState.value = EXPLANATION_TERMINAL_STATUSES.has(result.status) ? 'complete' : 'polling'
    if (!EXPLANATION_TERMINAL_STATUSES.has(result.status)) scheduleExplanationPoll(activeSession)
    else clearExplanationPollTimer()
  } catch (err) {
    if (activeSession !== sessionId) return
    explanationError.value = '智能体解释暂时读取失败，将自动重试'
    explanationState.value = 'retrying'
    scheduleExplanationPoll(activeSession)
  }
}

async function refreshEvent(activeSession, initial = false) {
  if (activeSession !== sessionId) return
  if (initial) loading.value = true
  else syncState.value = 'polling'

  try {
    const eventId = route.params.eventId || 'event-fall-100'
    const nextEvent = await getEvent(eventId)
    if (activeSession !== sessionId) return
    event.value = nextEvent
    forewarningSnapshots.value = nextEvent.forewarning_snapshots || []
    void syncAsset(nextEvent, activeSession)
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
  clearExplanationPollTimer()
  event.value = null
  forewarningSnapshots.value = []
  explanation.value = null
  explanationError.value = ''
  explanationState.value = 'loading'
  error.value = ''
  syncWarning.value = ''
  syncState.value = 'loading'
  highRiskAcknowledged.value = false
  highRiskDialogVisible.value = false
  traceOpen.value = false
  selectedEvidence.value = null
  asset.value = null
  assetId.value = null
  assetState.value = 'idle'
  assetMessage.value = ''
  submittingResidentResponse.value = false
  residentResponseRecorded.value = false
  submittingIntervention.value = false
  interventionRequested.value = false
  if (!route.params.eventId) {
    loading.value = false
    error.value = route.query.reason === 'unavailable'
      ? '风险事件调取失败：后端接口服务不可达，请检查后端服务和网络连接'
      : '风险事件调取失败：当前居民暂无可用事件'
    syncState.value = 'idle'
    return
  }
  void refreshEvent(activeSession, true)
  void refreshExplanation(activeSession, true)
}

function stopEventSession() {
  sessionId += 1
  clearPollTimer()
  clearExplanationPollTimer()
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

async function requestIntervention() {
  if (!event.value || submittingIntervention.value || interventionRequested.value) return
  submittingIntervention.value = true
  try {
    const result = await interveneEvent(event.value.event_id)
    const interventions = event.value.interventions || (event.value.interventions = [])
    const existingIndex = interventions.findIndex((item) => item.result_id === result.result_id)
    if (existingIndex >= 0) interventions.splice(existingIndex, 1, result)
    else interventions.push(result)
    interventionRequested.value = true
    ElMessage.success('干预请求已由后端受理')
  } catch (err) {
    ElMessage.error(`干预请求失败：${err.message}`)
  } finally {
    submittingIntervention.value = false
  }
}

watch(() => [route.params.eventId, route.query.reason, runtime.mode], startEventSession, { immediate: true })
watch(event, (nextEvent) => {
  if (!nextEvent || highRiskAcknowledged.value) return
  if (['ORANGE', 'RED'].includes(nextEvent.risk_level) || Number(nextEvent.risk_score) >= 0.7) {
    highRiskDialogVisible.value = true
    playHighRiskTone()
  }
}, { deep: true })
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
      <el-dialog
        v-model="highRiskDialogVisible"
        width="min(92vw, 520px)"
        class="high-risk-dialog"
        :show-close="false"
        :close-on-click-modal="false"
        :close-on-press-escape="false"
        destroy-on-close
      >
        <template #header>
          <div class="high-risk-dialog-header"><el-icon><WarningFilled /></el-icon><span>高风险告警</span></div>
        </template>
        <div class="high-risk-dialog-body">
          <strong>{{ event.title }}</strong>
          <p>{{ event.recommended_action || '请先确认老人安全，并联系家属或紧急联系人。' }}</p>
        </div>
        <template #footer><el-button type="danger" size="large" @click="acknowledgeHighRisk">我已看到，查看处理建议</el-button></template>
      </el-dialog>
      <section class="event-summary-card" data-testid="risk-engine-panel">
        <div class="event-summary-main">
          <span class="section-kicker">风险评估结果</span>
          <div class="summary-badges">
            <RiskBadge :level="event.risk_level" :score="formatRiskScore(event.risk_score)" />
            <el-tag size="large" effect="plain">{{ statusLabel(event.status) }}</el-tag>
            <SourceBadge :mode="event.source_mode" :simulated="event.simulated" />
          </div>
          <h2>{{ event.title }}</h2>
          <p>{{ event.recommended_action }}</p>
          <div class="meta-line">
            <span>事件 {{ event.event_id }}</span><span>风险等级 {{ displayValueLabel(event.risk_level) }}</span><span>事件状态 {{ statusLabel(event.status) }}</span><span>规则版本 {{ event.ruleset_version }}</span><span>{{ formatDateTime(event.created_at) }}</span>
          </div>
        </div>
        <div class="event-score"><span>{{ formatRiskScore(event.risk_score) }}</span><small>风险分数</small></div>
      </section>

      <MediaPanel v-if="assetState === 'ready'" :asset="asset" :source-mode="event.source_mode" :simulated="event.simulated" />
      <el-alert v-else-if="assetState === 'missing'" :title="assetMessage" type="warning" show-icon :closable="false" data-testid="asset-status" />
      <el-alert v-else-if="assetState === 'failed'" :title="assetMessage" type="error" show-icon :closable="false" data-testid="asset-status" />
      <el-alert v-else-if="assetState === 'idle'" title="暂无可追溯视频" type="info" show-icon :closable="false" data-testid="asset-status" />

      <section v-if="preInterventionSnapshot" class="content-card forewarning-closure-card" data-testid="forewarning-closure-panel">
        <div class="card-heading">
          <div><span class="section-kicker">工程风险指数 · 非概率</span><h2>干预前后观察对比</h2></div>
          <el-tag :type="postInterventionSnapshot ? 'success' : 'warning'" effect="plain">
            {{ postInterventionSnapshot ? '已取得恢复快照' : '等待恢复快照' }}
          </el-tag>
        </div>
        <div class="forewarning-closure-grid">
          <article>
            <small>干预前即时指数</small>
            <strong>{{ formatRiskScore(preInterventionSnapshot.instant.engineering_index) }}</strong>
            <span>{{ assessmentLabel(preInterventionSnapshot.assessment_status) }} · 置信 {{ displayValueLabel(preInterventionSnapshot.confidence_level) }}</span>
          </article>
          <article>
            <small>干预后即时指数</small>
            <strong>{{ postInterventionSnapshot ? formatRiskScore(postInterventionSnapshot.instant.engineering_index) : '—' }}</strong>
            <span>{{ postInterventionSnapshot ? `${assessmentLabel(postInterventionSnapshot.assessment_status)} · 置信 ${postInterventionSnapshot.confidence_level}` : '继续观察中' }}</span>
          </article>
          <article>
            <small>指数变化</small>
            <strong>{{ forewarningDelta === null ? '—' : `${forewarningDelta > 0 ? '+' : ''}${Math.round(forewarningDelta * 100)}` }}</strong>
            <span>{{ forewarningDelta === null ? '尚不可比较' : forewarningDelta <= 0 ? '工程指数回落' : '仍需继续观察' }}</span>
          </article>
          <article class="forewarning-components">
            <small>干预前四分量</small>
            <span>人体 {{ formatRiskScore(preInterventionSnapshot.components.human_risk) }}</span>
            <span>个人 {{ formatRiskScore(preInterventionSnapshot.components.personal_deviation) }}</span>
            <span>环境 {{ formatRiskScore(preInterventionSnapshot.components.environment_risk) }}</span>
            <span>交互 {{ formatRiskScore(preInterventionSnapshot.components.interaction_risk) }}</span>
          </article>
        </div>
        <el-alert
          v-if="preInterventionSnapshot.degradation_reasons.length"
          :title="`降级原因：${preInterventionSnapshot.degradation_reasons.join(' · ')}`"
          type="warning"
          show-icon
          :closable="false"
        />
      </section>

      <section class="content-card agent-explanation-card" data-testid="agent-explanation-panel">
        <div class="card-heading">
          <div><span class="section-kicker">解释与建议</span><h2>为什么这样建议</h2></div>
          <el-tag v-if="explanation" :type="explanationStatusMeta.type" effect="plain" data-testid="agent-explanation-status">
            {{ explanationStatusMeta.label }}
          </el-tag>
        </div>
        <el-alert v-if="explanationError" :title="explanationError" type="warning" show-icon :closable="false" data-testid="agent-explanation-error" />
        <el-alert v-else-if="!explanation || ['PENDING', 'PROCESSING'].includes(explanation.status)" title="解释生成中" type="info" show-icon :closable="false" data-testid="agent-explanation-pending" />
        <el-alert v-else-if="explanation.status === 'RETRY'" title="解释生成重试中" type="warning" show-icon :closable="false" data-testid="agent-explanation-retry" />
        <el-alert v-else-if="explanation.status === 'NOT_REQUESTED'" title="暂无智能体解释" type="info" show-icon :closable="false" data-testid="agent-explanation-not-requested" />
        <el-alert v-else-if="explanation.status === 'FAILED'" title="解释生成失败，但风险事件与依据仍正常展示。" type="error" show-icon :closable="false" data-testid="agent-explanation-failed" />
        <div v-else-if="explanation.explanation" class="agent-explanation-content" data-testid="agent-explanation-content">
          <div class="agent-explanation-narrative">
            <h3>{{ explanation.explanation.summary }}</h3>
            <ul>
              <li v-for="(point, index) in explanation.explanation.reasoning_points" :key="`${index}-${point}`">{{ point }}</li>
            </ul>
            <p><strong>建议：</strong>{{ explanation.explanation.recommended_action_text }}</p>
            <p class="agent-capability-notice">{{ explanation.explanation.capability_notice }}</p>
          </div>
          <div class="agent-explanation-side">
            <dl class="detail-list agent-explanation-meta">
              <div><dt>生成来源</dt><dd data-testid="agent-explanation-generated-by">{{ explanationGeneratedBy }}</dd></div>
              <div><dt>是否使用降级解释</dt><dd data-testid="agent-explanation-fallback-used">{{ explanationFallbackUsed ? '是' : '否' }}</dd></div>
              <div><dt>创建时间（北京时间）</dt><dd data-testid="agent-explanation-created-at">{{ formatDateTime(explanation.created_at) }}</dd></div>
              <div><dt>完成时间（北京时间）</dt><dd data-testid="agent-explanation-completed-at">{{ formatDateTime(explanation.completed_at) }}</dd></div>
            </dl>
            <el-tag v-if="explanationFallbackUsed" type="warning" effect="plain" data-testid="agent-explanation-fallback">模板降级解释</el-tag>
          </div>
        </div>
      </section>

      <section v-if="hasDetailGridContent" class="event-detail-grid" data-testid="event-detail-grid">
        <div v-if="hasPrimaryDetailContent" class="event-primary-column">
          <article v-if="displayEvidences.length" class="content-card" data-testid="evidence-panel">
            <div class="card-heading"><div><span class="section-kicker">依据</span><h2>为什么系统建议关注</h2></div><span>{{ event.evidence_summary.length }} 条依据</span></div>
            <div class="evidence-grid">
              <article v-for="evidence in displayEvidences" :key="evidence.evidence_id" class="evidence-card">
                <div class="evidence-top"><code>{{ evidenceTypeLabel(evidence.evidence_type) }}</code><span>{{ timeScaleLabel(evidence.time_scale) }}</span></div>
                <h3>{{ evidence.explanation }}</h3>
                <div class="evidence-metrics display-grid">
                  <span><small>当前值</small><b>{{ evidence.current_value ?? '—' }}</b></span>
                  <span><small>个人基线</small><b>{{ evidence.baseline_value ?? '—' }}</b></span>
                  <span><small>异常程度</small><b>{{ formatPercent(evidence.severity) }}</b></span>
                  <span><small>置信度</small><b>{{ formatPercent(evidence.confidence) }}</b></span>
                  <span><small>数据质量</small><b>{{ formatPercent(evidence.data_quality) }}</b></span>
                </div>
                <div class="evidence-trace-summary">
                  <span>{{ (evidence.observation_ids || []).length }} 条原始观测</span>
                  <span>{{ evidence.adapter_version || '暂无适配器详情' }}</span>
                </div>
                <SourceBadge v-if="evidence.source_mode" :mode="evidence.source_mode" :simulated="evidence.simulated" />
                <el-button v-if="evidence.observation_ids?.length" class="trace-button" size="large" plain @click="openTrace(evidence)">查看原始观测</el-button>
              </article>
            </div>
          </article>

          <TechnicalDisclosure v-if="displayRuleTraces.length" title="规则判断与质量门槛" summary="状态迁移、评分分量、个人基线和查询窗口">
          <article class="content-card" data-testid="rule-trace-panel">
            <div class="card-heading"><div><span class="section-kicker">规则轨迹</span><h2>后端实际规则判断</h2></div><span>{{ displayRuleTraces.length }} 次评估</span></div>
            <div class="tool-results">
              <article v-for="trace in displayRuleTraces" :key="trace.trace_id">
                <el-tag effect="dark">{{ trace.matched_rule }}</el-tag>
                <h3>{{ trace.reason || '后端未返回规则解释' }}</h3>
                <dl class="detail-list">
                  <div><dt>状态迁移</dt><dd>{{ displayValueLabel(trace.previous_status || trace.previous_state) }} → {{ displayValueLabel(trace.next_status || trace.next_state) }}</dd></div>
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
          </TechnicalDisclosure>

          <article v-if="event.timeline?.length" class="content-card" data-testid="event-action-panel">
            <div class="card-heading"><div><span class="section-kicker">系统动作</span><h2>干预与观察时间轴</h2></div></div>
            <el-timeline class="action-timeline" data-testid="event-action-timeline">
              <el-timeline-item v-for="item in event.timeline" :key="`${item.time}-${item.title}`" :timestamp="item.time" placement="top">
                <div class="timeline-card"><strong>{{ item.title }}</strong><p>{{ item.detail }}</p><el-tag effect="plain" :type="item.kind === 'FAMILY_FEEDBACK' ? 'warning' : undefined">{{ item.kind === 'FAMILY_FEEDBACK' ? '家属记录' : displayValueLabel(item.status) }}</el-tag></div>
              </el-timeline-item>
            </el-timeline>
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

        <aside v-if="hasAsideDetailContent" class="event-aside">
          <section v-if="['OPEN', 'INTERVENING'].includes(event.status)" class="content-card intervention-action-card" data-testid="intervention-action-panel">
            <div class="card-heading"><div><span class="section-kicker">处理动作</span><h2>联系与干预</h2></div></div>
            <p>由后端选择并执行已批准的干预工具，页面不会根据智能体解释自动触发。</p>
            <el-button
              data-testid="intervention-submit"
              type="warning"
              size="large"
              :loading="submittingIntervention"
              :disabled="interventionRequested"
              @click="requestIntervention"
            >
              {{ interventionRequested ? '干预请求已提交（已受理）' : '查看处理建议' }}
            </el-button>
          </section>

          <section v-if="event.interventions?.length" class="content-card tool-card" data-testid="intervention-result-panel">
            <div class="card-heading"><div><span class="section-kicker">工具结果</span><h2>执行记录</h2></div></div>
            <div class="tool-results">
              <article v-for="result in event.interventions" :key="result.result_id">
                <el-tag :type="DELIVERY_STATUSES[result.delivery_status]?.type || 'info'" size="large" effect="dark">
                  {{ DELIVERY_STATUSES[result.delivery_status]?.label || displayValueLabel(result.delivery_status) }}
                </el-tag>
                <h3>{{ displayValueLabel(result.tool_name) }}</h3>
                <dl class="detail-list">
                  <div><dt>执行方式</dt><dd>{{ displayValueLabel(result.action_type) }}</dd></div>
                  <div><dt>老人反馈</dt><dd>{{ result.resident_response || '暂无' }}</dd></div>
                  <div v-if="result.family_feedback"><dt>家属反馈</dt><dd>{{ result.family_feedback }}</dd></div>
                  <div><dt>干预后水位</dt><dd>{{ formatRiskScore(result.risk_after) }}</dd></div>
                  <div><dt>是否解除</dt><dd>{{ result.resolved ? '是' : '否' }}</dd></div>
                  <div><dt>结果</dt><dd>{{ result.resolution_reason || '等待结果' }}</dd></div>
                </dl>
                <el-alert v-if="result.delivery_status === 'FAILED'" title="工具调用失败已如实保留，未标记为干预成功。" type="error" show-icon :closable="false" />
              </article>
            </div>
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
            <p v-if="residentResponseRecorded" class="elder-action-note">确认不会直接关闭事件，仍由后端依据和观察期决定风险是否回落。</p>
          </section>
        </aside>
      </section>

      <el-drawer v-model="traceOpen" title="依据的详细来源" size="520px">
        <div v-if="selectedEvidence" class="trace-drawer" data-testid="evidence-trace">
          <SourceBadge :mode="selectedEvidence.source_mode" :simulated="selectedEvidence.simulated" />
          <h2>{{ evidenceTypeLabel(selectedEvidence.evidence_type) }}</h2>
          <p>{{ selectedEvidence.explanation }}</p>
          <dl class="detail-list">
            <div><dt>依据标识</dt><dd>{{ selectedEvidence.evidence_id }}</dd></div>
            <div><dt>风险方向</dt><dd>{{ domainLabel(selectedEvidence.risk_domain) }}</dd></div>
            <div><dt>生成时间</dt><dd>{{ formatDateTime(selectedEvidence.timestamp) }}</dd></div>
            <div><dt>适配器版本</dt><dd>{{ selectedEvidence.adapter_version }}</dd></div>
            <div><dt>个人基线</dt><dd>{{ selectedEvidence.baseline_value ?? '—' }}</dd></div>
            <div><dt>当前值</dt><dd>{{ selectedEvidence.current_value ?? '—' }}</dd></div>
            <div><dt>基线偏离</dt><dd>{{ selectedEvidence.baseline_deviation ?? '—' }}</dd></div>
          </dl>
          <h3>关联活动记录</h3>
          <article v-for="observation in selectedObservations" :key="observation.observation_id" class="observation-card">
            <strong>{{ evidenceTypeLabel(observation.feature_name) }}</strong>
            <code>{{ observation.observation_id }}</code>
            <p>{{ observation.feature_value }} {{ unitLabel(observation.unit) }} · {{ formatDateTime(observation.timestamp) }}</p>
            <dl class="detail-list compact-list">
              <div><dt>来源</dt><dd>{{ displayValueLabel(observation.source) }}</dd></div>
              <div><dt>置信度</dt><dd>{{ formatPercent(observation.confidence) }}</dd></div>
              <div><dt>质量</dt><dd>{{ formatPercent(observation.data_quality) }}</dd></div>
              <div><dt>素材标识</dt><dd>{{ formatAssetId(observation.asset_id) }}</dd></div>
            </dl>
          </article>
          <el-alert v-if="!selectedObservations.length" title="接口尚未返回关联原始观测，当前只能追溯到依据标识。" type="warning" show-icon :closable="false" />
        </div>
      </el-drawer>
    </template>
  </div>
</template>
