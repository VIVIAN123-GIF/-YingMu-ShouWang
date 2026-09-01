<script setup>
import { computed, onMounted, ref } from 'vue'
import MediaPanel from '../components/common/MediaPanel.vue'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ReplaySelector from '../components/replay/ReplaySelector.vue'
import { getAsset, getEvent, getEvents } from '../services/repository'
import { resolveEventAssetId } from '../services/viewModel'
import { formatDateTime } from '../utils/format'

const loading = ref(true)
const error = ref('')
const events = ref([])
const selectedId = ref('')
const selected = ref(null)
const selectedAsset = ref(null)
const assetState = ref('idle')
const assetMessage = ref('')
let selectionVersion = 0
const selectable = computed(() => events.value.filter((event) => event.primary_domain !== 'SYSTEM').sort((left, right) => new Date(left.created_at) - new Date(right.created_at)))
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
  const assetId = resolveEventAssetId(event)
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
    <PageHeader title="事件影像回看" description="实时事件与授权片段共用同一索引，每条记录保留独立的数据来源与授权标记。">
      <SourceBadge v-if="selected" :mode="selected.source_mode" :simulated="selected.simulated" />
    </PageHeader>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="events.length">
      <ReplaySelector v-model="selectedId" :events="selectable" @select="select" />
      <div v-if="selected" class="replay-stage">
      <MediaPanel v-if="selectedAsset" :asset="selectedAsset" :source-mode="selected?.source_mode" :simulated="selected?.simulated" />
      <el-alert v-else-if="assetState === 'failed'" :title="assetMessage" type="error" :closable="false" show-icon />
      <section v-if="selected" v-loading="assetState === 'loading'" class="content-card" :class="{ 'replay-detail-wide': !selectedAsset }" data-testid="replay-detail">
        <div class="card-heading replay-detail-heading">
          <div><span class="section-kicker">当前片段</span><h2>{{ selected.title }}</h2></div>
          <RiskBadge :level="selected.risk_level" text-only />
        </div>
        <SourceBadge button class="replay-detail-source" :mode="selected.source_mode" :simulated="selected.simulated" />
        <el-timeline v-if="selected.timeline?.length" class="replay-detail-timeline">
          <el-timeline-item v-for="item in selected.timeline" :key="`${item.time}-${item.title}`" :timestamp="formatDateTime(item.time)" placement="top">
            <strong>{{ item.title }}</strong><p>{{ item.detail }}</p>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="当前事件暂无回放时间轴" />
      </section>
      </div>
      <el-empty v-else class="content-card replay-empty" description="请选择场景查看关键片段" />
    </template>
  </div>
</template>
