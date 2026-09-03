<script setup>
import { computed, onMounted, ref } from 'vue'
import MediaPanel from '../components/common/MediaPanel.vue'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ReplaySelector from '../components/replay/ReplaySelector.vue'
import { getAsset, getEvent, getEvents, getSelectedEventMedia } from '../services/repository'
import { mergeDuplicateReplayOptions, resolveEventAssetId } from '../services/viewModel'
import { displayValueLabel, domainLabel, evidenceTypeLabel, formatDateTime, formatPercent, formatRiskScore, statusLabel } from '../utils/format'

const loading = ref(true)
const error = ref('')
const events = ref([])
const selectedId = ref('')
const selected = ref(null)
const selectedAsset = ref(null)
const assetState = ref('idle')
const assetMessage = ref('')
let selectionVersion = 0
const FACTOR_LABELS = Object.freeze({
  human_instability: '人体不稳定',
  human_environment_interaction: '人-环境交互',
  personal_baseline_deviation: '个人基线偏离',
  rapid_rise: '快速起身',
  trunk_sway: '躯干摇晃',
  lateral_drift: '横向漂移',
  personal_deviation: '个人基线偏离',
  environment_risk: '环境风险',
  interaction_risk: '交互风险',
  quality_penalty: '质量降级',
})
const selectable = computed(() => mergeDuplicateReplayOptions(
  events.value.filter((event) => event.primary_domain !== 'SYSTEM'),
).sort((left, right) => new Date(left.created_at) - new Date(right.created_at)))
const factorContributions = computed(() => {
  const snapshots = selected.value?.forewarning_snapshots || []
  const snapshot = snapshots.find((item) => item?.phase === 'PRE_INTERVENTION' && item?.dominant_factors?.length)
    || snapshots.find((item) => item?.dominant_factors?.length)
  if (snapshot) {
    return snapshot.dominant_factors.map((item) => (typeof item === 'string' ? { factor: item, contribution: null } : item))
  }
  const trace = [...(selected.value?.rule_traces || [])].reverse().find((item) => item?.context_snapshot?.contributions)
  return Object.entries(trace?.context_snapshot?.contributions || {})
    .filter(([, contribution]) => Number(contribution) > 0)
    .map(([factor, contribution]) => ({ factor, contribution: Number(contribution) }))
})
const evidenceItems = computed(() => selected.value?.evidence_summary || [])
function formatTimelineTime(value) {
  return /^\d{2}:\d{2}/.test(String(value || '')) ? value : formatDateTime(value)
}
async function load() { try { events.value = await getEvents(); selectedId.value = selectable.value[0]?.event_id || ''; await select(selectedId.value) } catch (err) { error.value = `无法读取场景回放：${err.message}` } finally { loading.value = false } }
async function select(eventId) {
  if (!eventId) return
  const activeVersion = ++selectionVersion
  selectedId.value = eventId
  selectedAsset.value = null
  assetMessage.value = ''
  const event = await getEvent(eventId)
  if (activeVersion !== selectionVersion) return
  selected.value = event
  // Controlled replay events use the verified selected primary clip. Real
  // LIVE_DEVICE records have no selected mapping and retain their private asset.
  const assetId = getSelectedEventMedia(event)?.primary_asset_id || resolveEventAssetId(event)
  if (!assetId) {
    assetState.value = 'idle'
    return
  }
  assetState.value = 'loading'
  try {
    const asset = await getAsset(assetId)
    if (activeVersion !== selectionVersion) return
    selectedAsset.value = asset
    assetState.value = 'ready'
  } catch (err) {
    if (activeVersion !== selectionVersion) return
    assetState.value = 'failed'
    assetMessage.value = `素材读取失败（${assetId}）：${err.message}`
  }
}
onMounted(load)
</script>

<template>
  <div v-loading="loading" data-testid="replay-view">
    <PageHeader title="风险验证与回放" description="对照高低风险记录，查看风险读数、影响因子、处置建议与授权片段。">
      <SourceBadge v-if="selected" :mode="selected.source_mode" :simulated="selected.simulated" />
    </PageHeader>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="events.length">
      <ReplaySelector v-model="selectedId" :events="selectable" @select="select" />
      <div v-if="selected" class="replay-stage">
      <MediaPanel v-if="selectedAsset" :asset="selectedAsset" :source-mode="selected?.source_mode" :simulated="selected?.simulated" />
      <el-alert v-else-if="assetState === 'failed'" :title="assetMessage" type="error" :closable="false" show-icon />
      <el-alert v-else-if="assetState === 'idle'" title="当前记录暂无可回放视频，风险与处置记录仍可查看" type="info" :closable="false" show-icon />
      <section v-if="selected" v-loading="assetState === 'loading'" class="content-card" :class="{ 'replay-detail-wide': !selectedAsset }" data-testid="replay-detail">
        <div class="card-heading replay-detail-heading">
          <div><span class="section-kicker">当前片段</span><h2>{{ selected.title }}</h2></div>
          <RiskBadge :level="selected.risk_level" text-only />
        </div>
        <SourceBadge button class="replay-detail-source" :mode="selected.source_mode" :simulated="selected.simulated" />
        <div class="replay-metric-grid" data-testid="replay-metrics">
          <article><small>风险分数</small><strong>{{ formatRiskScore(selected.risk_score) }}</strong></article>
          <article><small>风险领域</small><strong>{{ domainLabel(selected.primary_domain) }}</strong></article>
          <article><small>事件状态</small><strong>{{ statusLabel(selected.status) }}</strong></article>
          <article><small>事件时间</small><strong>{{ formatDateTime(selected.created_at) }}</strong></article>
        </div>
        <div class="replay-action-panel">
          <small>对应干预动作</small>
          <strong>{{ selected.recommended_action || '保持观察并由家属确认当前状态。' }}</strong>
        </div>
        <div v-if="factorContributions.length" class="replay-factor-panel" data-testid="replay-factor-contributions">
          <small>主导风险因子贡献</small>
          <div v-for="item in factorContributions" :key="item.factor" class="replay-factor-row">
            <span>{{ FACTOR_LABELS[item.factor] || displayValueLabel(item.factor) }}</span>
            <strong>{{ item.contribution === null || item.contribution === undefined ? '已命中' : formatPercent(item.contribution) }}</strong>
          </div>
        </div>
        <div class="replay-evidence-panel" data-testid="replay-evidence-summary">
          <small>进入系统的证据</small>
          <div v-if="evidenceItems.length" class="replay-evidence-list">
            <article v-for="item in evidenceItems" :key="item.evidence_id || item.evidence_type">
              <strong>{{ evidenceTypeLabel(item.evidence_type) }}</strong><span>{{ item.explanation }}</span>
            </article>
          </div>
          <p v-else>本次记录为低风险对照，系统未形成需要处置的异常证据。</p>
        </div>
        <div class="replay-timeline-heading"><small>规则与干预时间轴</small></div>
        <el-timeline v-if="selected.timeline?.length" class="replay-detail-timeline">
          <el-timeline-item v-for="item in selected.timeline" :key="`${item.time}-${item.title}`" :timestamp="formatTimelineTime(item.time)" placement="top">
            <strong>{{ item.title }}</strong><p>{{ item.detail }}</p>
          </el-timeline-item>
        </el-timeline>
        <p v-else class="replay-timeline-fallback">当前状态、证据和建议已完整保留；该对照记录没有额外状态流转。</p>
        <router-link class="replay-detail-link" :to="`/events/${selected.event_id}`">查看完整依据、风险事件与规则轨迹</router-link>
      </section>
      </div>
      <el-empty v-else class="content-card replay-empty" description="请选择场景查看关键片段" />
    </template>
    <el-empty v-else-if="!loading && !error" class="content-card replay-empty" description="暂无可验证的风险记录" />
  </div>
</template>
