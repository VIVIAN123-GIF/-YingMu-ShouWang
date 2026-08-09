<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ChartPanel from '../components/common/ChartPanel.vue'
import MediaPanel from '../components/common/MediaPanel.vue'
import { DELIVERY_STATUSES } from '../domain/constants'
import { getAsset, getEvent, runtime, submitInterventionResult } from '../services/repository'
import { domainLabel, formatAssetId, formatDateTime, formatPercent, formatRiskScore, statusLabel } from '../utils/format'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const event = ref(null)
const asset = ref(null)
const assetNotice = ref('')
const traceOpen = ref(false)
const selectedEvidence = ref(null)
const syncState = ref('loading')
const syncWarning = ref('')
const submittingResidentResponse = ref(false)
const residentResponseRecorded = ref(false)

const POLL_INTERVAL_MS = 1500
const TERMINAL_STATUSES = new Set(['RESOLVED', 'ESCALATED', 'FALSE_ALARM'])
let pollTimer = null
let sessionId = 0
let settledAssetId = null

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

const mediaAsset = computed(() => asset.value || {
  title: '事件画面',
  source_mode: event.value?.source_mode || 'MOCK',
  simulated: event.value?.simulated ?? true,
  available: false,
  notice: assetNotice.value || '关联 Observation 未提供可追溯素材。',
})

const selectedObservations = computed(() => {
  const ids = new Set(selectedEvidence.value?.observation_ids || [])
  return (event.value?.observations || []).filter((observation) => ids.has(observation.observation_id))
})

function observationAssetIdFor(evidence, currentEvent = event.value) {
  const ids = new Set(evidence?.observation_ids || [])
  return (currentEvent?.observations || []).find((observation) => (
    ids.has(observation.observation_id)
    && typeof observation.asset_id === 'string'
    && observation.asset_id.length > 0
  ))?.asset_id || null
}

function firstEventAssetId(currentEvent) {
  return (currentEvent?.evidences || [])
    .map((evidence) => observationAssetIdFor(evidence, currentEvent))
    .find(Boolean) || null
}

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

async function syncAsset(currentEvent, activeSession) {
  const assetId = firstEventAssetId(currentEvent)
  if (!assetId) {
    settledAssetId = null
    asset.value = null
    assetNotice.value = '关联 Observation 未提供可追溯素材，事件证据和状态仍可查看。'
    return
  }
  if (assetId === settledAssetId) return

  asset.value = null
  assetNotice.value = ''
  try {
    const nextAsset = await getAsset(assetId)
    if (activeSession !== sessionId || firstEventAssetId(event.value) !== assetId) return
    settledAssetId = assetId
    asset.value = nextAsset
  } catch (assetError) {
    if (activeSession !== sessionId || firstEventAssetId(event.value) !== assetId) return
    if (assetError?.response?.status === 404) settledAssetId = assetId
    assetNotice.value = `后端暂无素材记录（${assetId}），事件证据和状态仍可查看。`
  }
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
    await syncAsset(nextEvent, activeSession)
    if (activeSession !== sessionId) return

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
  settledAssetId = null
  event.value = null
  asset.value = null
  assetNotice.value = ''
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
                  <span>{{ formatAssetId(observationAssetIdFor(evidence)) }}</span>
                  <span>{{ evidence.adapter_version || '暂无适配器详情' }}</span>
                </div>
                <SourceBadge v-if="evidence.source_mode" :mode="evidence.source_mode" :simulated="evidence.simulated" />
                <el-button v-if="evidence.observation_ids?.length" class="trace-button" size="large" plain @click="openTrace(evidence)">查看原始观测</el-button>
              </article>
            </div>
            <el-empty v-else description="该绿色事件没有异常 Evidence" />
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
          <MediaPanel :asset="mediaAsset" :source-mode="event.source_mode" :simulated="event.simulated" />

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
            <div><dt>素材 ID</dt><dd>{{ formatAssetId(observationAssetIdFor(selectedEvidence)) }}</dd></div>
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
              <div><dt>素材</dt><dd>{{ formatAssetId(observation.asset_id) }}</dd></div>
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
