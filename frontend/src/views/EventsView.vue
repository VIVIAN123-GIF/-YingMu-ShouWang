<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import { ALARM_TASK_STATUSES, EVENT_STATUSES, RISK_DOMAINS, RISK_LEVELS, SOURCE_MODES } from '../domain/constants'
import { getAlarmProcessingTasks, getEvents, getRiskReviews, RESIDENT_ID, runtime } from '../services/repository'
import { displayValueLabel, domainLabel, evidenceTypeLabel, formatDateTime, formatRiskScore, statusLabel } from '../utils/format'
import { groupOptionsByLabel, matchesGroupedOption } from '../utils/options'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const events = ref([])
const reviews = ref([])
const filters = ref({ domain: '', level: '', status: '', source: '' })
const alarmTasks = ref([])
const alarmLoading = ref(false)
const alarmError = ref('')
let alarmTimer = null

const riskLevelOptions = computed(() => groupOptionsByLabel(RISK_LEVELS, (config) => config.label))
const sourceOptions = computed(() => groupOptionsByLabel(SOURCE_MODES, (config) => config.label))

const filteredEvents = computed(() => events.value
  .filter((event) => !filters.value.domain || event.primary_domain === filters.value.domain)
  .filter((event) => matchesGroupedOption(riskLevelOptions.value, filters.value.level, event.risk_level))
  .filter((event) => !filters.value.status || event.status === filters.value.status)
  .filter((event) => matchesGroupedOption(sourceOptions.value, filters.value.source, event.source_mode))
  .sort((left, right) => {
    const difference = new Date(right.created_at) - new Date(left.created_at)
    return difference || String(right.event_id).localeCompare(String(left.event_id))
  }))

const activeFilterCount = computed(() => Object.values(filters.value).filter(Boolean).length)

function clearFilters() {
  filters.value = { domain: '', level: '', status: '', source: '' }
}

async function load(background = false) {
  if (!background) loading.value = true
  try {
    const [nextEvents, nextReviews] = await Promise.all([getEvents(), getRiskReviews()])
    events.value = nextEvents
    reviews.value = nextReviews
    error.value = ''
  } catch (err) {
    error.value = `无法读取事件时间轴：${err.message}`
  } finally {
    if (!background) loading.value = false
  }
}

function stopAlarmPolling() {
  if (alarmTimer !== null) {
    window.clearTimeout(alarmTimer)
    alarmTimer = null
  }
}

function scheduleAlarmPolling() {
  stopAlarmPolling()
  if (runtime.mode === 'replay') return
  alarmTimer = window.setTimeout(() => {
    alarmTimer = null
    void load(true)
    void loadAlarmTasks()
  }, 5000)
}

async function loadAlarmTasks() {
  if (runtime.mode === 'replay') {
    alarmTasks.value = []
    stopAlarmPolling()
    return
  }
  alarmLoading.value = true
  try {
    alarmTasks.value = await getAlarmProcessingTasks({ residentId: RESIDENT_ID, limit: 20 })
    alarmError.value = ''
  } catch (err) {
    alarmError.value = `无法读取告警处理任务：${err.message}`
  } finally {
    alarmLoading.value = false
    scheduleAlarmPolling()
  }
}

onMounted(() => { void load(); void loadAlarmTasks() })
watch(() => runtime.mode, () => { void load(); void loadAlarmTasks() })
onBeforeUnmount(stopAlarmPolling)
</script>

<template>
  <div v-loading="loading" data-testid="events-view">
    <PageHeader title="老人活动事件记录" description="跌倒、心理趋势、访客交互和系统状态会按时间顺序记录。">
      <el-tag class="event-count-tag" size="large" effect="plain">{{ filteredEvents.length }} 条事件</el-tag>
    </PageHeader>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <section class="content-card alarm-processing-card" data-testid="risk-reviews">
      <div class="card-heading">
        <div><span class="section-kicker">规则复核</span><h2>不可判定与黄色观察</h2></div>
        <el-tag size="large" effect="plain">{{ reviews.length }} 条待复核</el-tag>
      </div>
      <div class="alarm-task-list">
        <article v-for="review in reviews" :key="review.trace_id" class="alarm-task-row">
          <div><strong>{{ evidenceTypeLabel(review.evidence_type) }}</strong><span>{{ review.explanation }}</span></div>
          <div><span>{{ formatDateTime(review.evaluated_at) }}</span><span>{{ review.matched_rule }}</span><span>{{ review.ruleset_version }}</span></div>
          <RiskBadge :level="review.risk_level" compact />
        </article>
        <el-empty v-if="!reviews.length && !loading" description="暂无需要人工复核的算法结果" />
      </div>
    </section>

    <section class="content-card alarm-processing-card" data-testid="alarm-processing">
      <div class="card-heading">
        <div><span class="section-kicker">告警处理队列</span><h2>设备告警处理任务</h2></div>
        <el-tag size="large" effect="plain">{{ alarmTasks.length }} 条任务</el-tag>
      </div>
      <el-alert v-if="alarmError" :title="alarmError" type="warning" show-icon :closable="false" />
      <div v-loading="alarmLoading" class="alarm-task-list">
        <article v-for="task in alarmTasks" :key="task.task_id" class="alarm-task-row">
          <div><strong>{{ task.alarm_ref }}</strong><span>{{ task.resident_id }} · {{ task.device_ref }}</span></div>
          <div><span>尝试 {{ task.attempt_count }}/{{ task.max_attempts }}</span><span>{{ task.capture_asset_id ? '已取得素材凭证' : '暂无素材凭证' }}</span></div>
          <el-tag :type="ALARM_TASK_STATUSES[task.status]?.type || 'info'" effect="plain">{{ ALARM_TASK_STATUSES[task.status]?.label || displayValueLabel(task.status) }}</el-tag>
        </article>
        <el-empty v-if="!alarmTasks.length && !alarmLoading" description="暂无待处理告警任务" />
      </div>
    </section>

    <section class="content-card timeline-filters" aria-label="时间轴筛选">
      <label><span>风险方向</span><el-select v-model="filters.domain" clearable placeholder="全部方向"><el-option v-for="(label, value) in RISK_DOMAINS" :key="value" :label="label" :value="value" /></el-select></label>
      <label><span>风险等级</span><el-select v-model="filters.level" clearable placeholder="全部等级"><el-option v-for="option in riskLevelOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select></label>
      <label><span>事件状态</span><el-select v-model="filters.status" clearable placeholder="全部状态"><el-option v-for="(label, value) in EVENT_STATUSES" :key="value" :label="label" :value="value" /></el-select></label>
      <label><span>数据来源</span><el-select v-model="filters.source" clearable placeholder="全部来源"><el-option v-for="option in sourceOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select></label>
      <el-button size="large" :disabled="!activeFilterCount" @click="clearFilters">清除筛选<span v-if="activeFilterCount">（{{ activeFilterCount }}）</span></el-button>
    </section>

    <section v-if="filteredEvents.length" class="unified-timeline" data-testid="unified-timeline">
      <article
        v-for="event in filteredEvents"
        :key="event.event_id"
        class="unified-event"
        :data-domain="event.primary_domain"
      >
        <div class="timeline-rail"><span :class="`node-${event.risk_level.toLowerCase()}`"></span></div>
        <time>{{ formatDateTime(event.created_at) }}</time>
        <button type="button" class="timeline-event-card" @click="router.push(`/events/${event.event_id}`)">
          <div class="timeline-event-heading">
            <div><span class="event-domain">{{ domainLabel(event.primary_domain) }}</span><h2>{{ event.title }}</h2></div>
            <RiskBadge :level="event.risk_level" compact />
          </div>
          <p>{{ event.recommended_action }}</p>
          <div class="timeline-event-footer">
            <span>{{ statusLabel(event.status) }}</span>
            <span>风险水位 {{ formatRiskScore(event.risk_score) }}</span>
            <span>{{ event.ruleset_version }}</span>
            <SourceBadge :mode="event.source_mode" :simulated="event.simulated" />
            <b>查看证据链 →</b>
          </div>
        </button>
      </article>
    </section>
    <el-empty v-else-if="!loading" description="当前筛选条件下没有事件"><el-button size="large" @click="clearFilters">查看全部事件</el-button></el-empty>
  </div>
</template>
