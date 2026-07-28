<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import { EVENT_STATUSES, RISK_DOMAINS, RISK_LEVELS, SOURCE_MODES } from '../domain/constants'
import { getEvents } from '../services/repository'
import { domainLabel, formatDateTime, formatRiskScore, statusLabel } from '../utils/format'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const events = ref([])
const filters = ref({ domain: '', level: '', status: '', source: '' })

const filteredEvents = computed(() => events.value
  .filter((event) => !filters.value.domain || event.primary_domain === filters.value.domain)
  .filter((event) => !filters.value.level || event.risk_level === filters.value.level)
  .filter((event) => !filters.value.status || event.status === filters.value.status)
  .filter((event) => !filters.value.source || event.source_mode === filters.value.source)
  .sort((left, right) => new Date(right.created_at) - new Date(left.created_at)))

const activeFilterCount = computed(() => Object.values(filters.value).filter(Boolean).length)

function clearFilters() {
  filters.value = { domain: '', level: '', status: '', source: '' }
}

async function load() {
  loading.value = true
  try {
    events.value = await getEvents()
  } catch (err) {
    error.value = `无法读取事件时间轴：${err.message}`
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" data-testid="events-view">
    <PageHeader title="统一事件时间轴" description="跌倒、心理趋势、访客交互和系统事件进入同一条时间轴。">
      <el-tag size="large" effect="plain">{{ filteredEvents.length }} 条事件</el-tag>
    </PageHeader>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <section class="content-card timeline-filters" aria-label="时间轴筛选">
      <label><span>风险方向</span><el-select v-model="filters.domain" clearable placeholder="全部方向"><el-option v-for="(label, value) in RISK_DOMAINS" :key="value" :label="label" :value="value" /></el-select></label>
      <label><span>风险等级</span><el-select v-model="filters.level" clearable placeholder="全部等级"><el-option v-for="(config, value) in RISK_LEVELS" :key="value" :label="config.label" :value="value" /></el-select></label>
      <label><span>事件状态</span><el-select v-model="filters.status" clearable placeholder="全部状态"><el-option v-for="(label, value) in EVENT_STATUSES" :key="value" :label="label" :value="value" /></el-select></label>
      <label><span>数据来源</span><el-select v-model="filters.source" clearable placeholder="全部来源"><el-option v-for="(config, value) in SOURCE_MODES" :key="value" :label="`${value} · ${config.label}`" :value="value" /></el-select></label>
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
