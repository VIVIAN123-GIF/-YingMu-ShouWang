<script setup>
import { computed, ref, watch } from 'vue'
import RiskBadge from '../common/RiskBadge.vue'
import SourceBadge from '../common/SourceBadge.vue'
import { ALARM_TASK_STATUSES, DELIVERY_STATUSES } from '../../domain/constants'
import { displayValueLabel, evidenceTypeLabel, formatDateTime, formatPercent, ruleLabel, statusLabel } from '../../utils/format'

const props = defineProps({
  runs: { type: Array, default: () => [] },
  loading: Boolean,
  error: { type: String, default: '' },
})

const highRunId = ref('')
const lowRunId = ref('')
const riskOrder = { UNKNOWN: 0, GREEN: 1, YELLOW: 2, ORANGE: 3, RED: 4 }
const factorLabels = {
  human_instability: '人体不稳定',
  personal_baseline_deviation: '个人基线偏离',
  environment_context: '环境风险',
  human_environment_interaction: '人-环境交互',
  data_quality_downgrade: '数据质量降级',
}
const metricUnits = { s: '秒', second: '秒', seconds: '秒', deg: '度', degree: '度', ratio: '' }

function newestFirst(left, right) {
  return Date.parse(right.captured_at) - Date.parse(left.captured_at)
}

function pairKey(run) {
  return [run.resident_id, run.device_ref, run.device_model, run.camera_position_id, run.authorization_ref].join('|')
}

function isHigh(run) {
  return riskOrder[run.risk_level] >= riskOrder.ORANGE
}

const realRuns = computed(() => props.runs
  .filter((run) => run.source_mode === 'LIVE_DEVICE' && run.simulated === false)
  .sort(newestFirst))
const lowRuns = computed(() => realRuns.value.filter((run) => !isHigh(run)))
const highRuns = computed(() => realRuns.value.filter((run) => (
  isHigh(run) && lowRuns.value.some((candidate) => pairKey(candidate) === pairKey(run))
)))
const selectedHigh = computed(() => highRuns.value.find((run) => run.run_id === highRunId.value) || null)
const matchingLowRuns = computed(() => selectedHigh.value
  ? lowRuns.value.filter((run) => pairKey(run) === pairKey(selectedHigh.value))
  : [])
const selectedLow = computed(() => matchingLowRuns.value.find((run) => run.run_id === lowRunId.value) || null)

watch(realRuns, () => {
  const latestHigh = highRuns.value[0]
  const currentHigh = highRuns.value.find((run) => run.run_id === highRunId.value)
  if (!currentHigh) {
    highRunId.value = latestHigh?.run_id || ''
  }
  if (!matchingLowRuns.value.some((run) => run.run_id === lowRunId.value)) {
    lowRunId.value = matchingLowRuns.value[0]?.run_id || ''
  }
}, { immediate: true })

watch(highRunId, () => {
  if (!matchingLowRuns.value.some((run) => run.run_id === lowRunId.value)) {
    lowRunId.value = matchingLowRuns.value[0]?.run_id || ''
  }
})

function optionLabel(run) {
  return `${run.run_id} · ${formatDateTime(run.captured_at)}`
}

function metricText(run, name) {
  const metric = run?.metrics?.[name]
  if (!metric) return '未提供'
  const state = metric.detected ? '已命中' : '未命中'
  if (metric.value === null || metric.value === undefined) return state
  const numeric = typeof metric.value === 'number' ? Number(metric.value.toFixed(3)) : metric.value
  return `${state} · ${numeric}${metricUnits[metric.unit] ?? metric.unit ?? ''}`
}

function factorItems(run) {
  const snapshots = run?.forewarning_snapshots || []
  const snapshot = snapshots.find((item) => item.phase === 'PRE_INTERVENTION' && item.dominant_factors?.length)
    || [...snapshots].reverse().find((item) => item.dominant_factors?.length)
  return snapshot?.dominant_factors || []
}

function taskResult(run) {
  const label = ALARM_TASK_STATUSES[run?.task_status]?.label || displayValueLabel(run?.task_status)
  const modules = (run?.task_result?.algorithm_summary?.modules || [])
    .map((item) => `${item.module} ${displayValueLabel(item.status)}`)
    .join(' / ')
  return modules ? `${label} · ${modules}` : label
}

function interventionResult(run) {
  const result = [...(run?.interventions || [])].reverse().find((item) => item.action_type !== 'family_feedback')
  if (!result) return run?.event ? '尚无干预结果' : '未创建风险事件，无需干预'
  const delivery = DELIVERY_STATUSES[result.delivery_status]?.label || displayValueLabel(result.delivery_status)
  const closure = result.resolved ? `已回落至 ${formatPercent(result.risk_after)}` : (result.resolution_reason || '继续观察')
  return `${delivery} · ${closure}`
}

function snapshotScore(snapshot) {
  return Math.max(
    snapshot.instant.engineering_index,
    snapshot.short_30s.engineering_index,
    snapshot.trend_3min.engineering_index,
  )
}

function recoveryDelta(run, snapshot) {
  const first = run?.forewarning_snapshots?.[0]
  if (!first) return null
  return snapshotScore(snapshot) - snapshotScore(first)
}
</script>

<template>
  <section class="content-card live-run-comparison" data-testid="live-run-comparison" v-loading="loading">
    <div class="card-heading">
      <div><span class="section-kicker">真实设备运行</span><h2>现场高低风险对照</h2></div>
      <SourceBadge mode="LIVE_DEVICE" :simulated="false" />
    </div>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <template v-else-if="highRuns.length && matchingLowRuns.length">
      <div class="live-run-selectors">
        <label><span>低风险运行 ID</span><el-select v-model="lowRunId" data-testid="low-run-select"><el-option v-for="run in matchingLowRuns" :key="run.run_id" :label="optionLabel(run)" :value="run.run_id" /></el-select></label>
        <label><span>高风险运行 ID</span><el-select v-model="highRunId" data-testid="high-run-select"><el-option v-for="run in highRuns" :key="run.run_id" :label="optionLabel(run)" :value="run.run_id" /></el-select></label>
      </div>

      <div class="live-run-table" role="table" aria-label="现场高低风险运行指标对照">
        <div class="live-run-row live-run-head" role="row">
          <strong role="columnheader">对照指标</strong>
          <div role="columnheader"><span>正常起身 / 正常行走</span><small>{{ selectedLow.run_id }}</small></div>
          <div role="columnheader"><span>快速起身后摇晃</span><small>{{ selectedHigh.run_id }}</small></div>
        </div>
        <div class="live-run-row" role="row"><strong role="rowheader">风险等级</strong><div role="cell"><RiskBadge :level="selectedLow.risk_level" compact /></div><div role="cell"><RiskBadge :level="selectedHigh.risk_level" compact /></div></div>
        <div class="live-run-row" role="row"><strong role="rowheader">峰值分数</strong><div role="cell">{{ formatPercent(selectedLow.risk_score) }}</div><div role="cell">{{ formatPercent(selectedHigh.risk_score) }}</div></div>
        <div class="live-run-row" role="row"><strong role="rowheader">rapid_rise</strong><div role="cell">{{ metricText(selectedLow, 'rapid_rise') }}</div><div role="cell">{{ metricText(selectedHigh, 'rapid_rise') }}</div></div>
        <div class="live-run-row" role="row"><strong role="rowheader">trunk_sway</strong><div role="cell">{{ metricText(selectedLow, 'trunk_sway') }}</div><div role="cell">{{ metricText(selectedHigh, 'trunk_sway') }}</div></div>
        <div class="live-run-row" role="row"><strong role="rowheader">数据质量</strong><div role="cell">{{ formatPercent(selectedLow.data_quality) }}</div><div role="cell">{{ formatPercent(selectedHigh.data_quality) }}</div></div>
        <div class="live-run-row" role="row"><strong role="rowheader">主导因子</strong><div role="cell"><span v-for="item in factorItems(selectedLow)" :key="item.factor" class="factor-value">{{ factorLabels[item.factor] || item.factor }} {{ formatPercent(item.contribution) }}</span><span v-if="!factorItems(selectedLow).length">无升级因子</span></div><div role="cell"><span v-for="item in factorItems(selectedHigh)" :key="item.factor" class="factor-value">{{ factorLabels[item.factor] || item.factor }} {{ formatPercent(item.contribution) }}</span><span v-if="!factorItems(selectedHigh).length">未提供</span></div></div>
        <div class="live-run-row" role="row"><strong role="rowheader">处理任务</strong><div role="cell">{{ taskResult(selectedLow) }}</div><div role="cell">{{ taskResult(selectedHigh) }}</div></div>
        <div class="live-run-row" role="row"><strong role="rowheader">干预结果</strong><div role="cell">{{ interventionResult(selectedLow) }}</div><div role="cell">{{ interventionResult(selectedHigh) }}</div></div>
      </div>

      <div class="live-run-provenance" data-testid="live-run-provenance">
        <span>设备 {{ selectedHigh.device_model }}</span><span>机位 {{ selectedHigh.camera_position_id }}</span><span>居民 {{ selectedHigh.resident_id }}</span><span>授权 {{ selectedHigh.authorization_ref }}</span>
      </div>

      <div class="live-run-evidence-grid">
        <section data-testid="live-run-evidence">
          <div class="subsection-heading"><span class="section-kicker">高风险真实输出</span><h3>Evidence 与 RuleTrace</h3></div>
          <div class="live-run-output-list">
            <article v-for="evidence in selectedHigh.evidences" :key="evidence.evidence_id"><strong>{{ evidenceTypeLabel(evidence.evidence_type) }}</strong><span>{{ evidence.explanation }}</span><small>{{ evidence.evidence_id }} · 质量 {{ formatPercent(evidence.data_quality) }}</small></article>
            <p v-if="!selectedHigh.evidences.length">本次运行未返回 Evidence。</p>
          </div>
          <div class="live-run-traces">
            <div v-for="trace in selectedHigh.rule_traces" :key="trace.trace_id"><strong>{{ ruleLabel(trace.matched_rule) }}</strong><span>{{ displayValueLabel(trace.previous_state) }} → {{ displayValueLabel(trace.next_state) }}</span><small>{{ trace.trace_id }}</small></div>
            <p v-if="!selectedHigh.rule_traces.length">本次运行未返回 RuleTrace。</p>
          </div>
        </section>

        <section data-testid="live-run-recovery">
          <div class="subsection-heading"><span class="section-kicker">闭环结果</span><h3>后续观察与风险回落</h3></div>
          <div class="recovery-snapshot-list">
            <article v-for="snapshot in selectedHigh.forewarning_snapshots" :key="snapshot.snapshot_id">
              <time>{{ formatDateTime(snapshot.evaluated_at) }}</time>
              <div><strong>{{ displayValueLabel(snapshot.phase) }}</strong><span>{{ formatPercent(snapshotScore(snapshot)) }}</span></div>
              <small>{{ statusLabel(selectedHigh.event?.status) }}<template v-if="recoveryDelta(selectedHigh, snapshot) !== null"> · 较首个快照 {{ recoveryDelta(selectedHigh, snapshot) > 0 ? '+' : '' }}{{ formatPercent(recoveryDelta(selectedHigh, snapshot)) }}</template></small>
            </article>
            <p v-if="!selectedHigh.forewarning_snapshots.length">本次运行尚无后续观察快照。</p>
          </div>
        </section>
      </div>
    </template>
    <el-empty v-else-if="!loading" description="尚无满足同一设备、机位、居民与授权条件的真实高低风险运行" :image-size="72" />
  </section>
</template>
