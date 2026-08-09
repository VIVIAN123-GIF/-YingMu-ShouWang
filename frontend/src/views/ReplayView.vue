<script setup>
import { computed, onMounted, ref } from 'vue'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import MediaPanel from '../components/common/MediaPanel.vue'
import { getAsset, getEvent, getEvents } from '../services/repository'

const loading = ref(true)
const error = ref('')
const events = ref([])
const selectedId = ref('')
const selected = ref(null)
const asset = ref(null)
const selectable = computed(() => events.value.filter((event) => event.primary_domain !== 'SYSTEM').sort((left, right) => new Date(left.created_at) - new Date(right.created_at)))
async function load() { try { events.value = await getEvents(); selectedId.value = selectable.value[0]?.event_id || ''; await select(selectedId.value) } catch (err) { error.value = `无法读取场景回放：${err.message}` } finally { loading.value = false } }
async function select(eventId) {
  if (!eventId) return
  selectedId.value = eventId
  selected.value = await getEvent(eventId)
  asset.value = null
  const assetId = selected.value.asset_id || selected.value.observations?.find((item) => item.asset_id)?.asset_id
  if (assetId) {
    try { asset.value = await getAsset(assetId) } catch { asset.value = null }
  }
}
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="场景回放" description="按故事顺序查看关键事件；每个片段都明确标记真实、回放、公开数据或 Mock 来源。"><SourceBadge v-if="selected" :mode="selected.source_mode" :simulated="selected.simulated" /></PageHeader>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="events.length"><section class="content-card"><div class="card-heading"><div><span class="section-kicker">选择场景</span><h2>100 天关键片段</h2></div><el-select v-model="selectedId" aria-label="选择回放场景" @change="select"><el-option v-for="(event, index) in selectable" :key="event.event_id" :label="`${index + 1}. ${event.title}`" :value="event.event_id" /></el-select></div><p>回放不会触发真实干预，也不会改变后端风险状态。</p></section><section v-if="selected" class="content-card" data-testid="replay-detail"><div class="card-heading"><div><span class="section-kicker">当前片段</span><h2>{{ selected.title }}</h2></div><RiskBadge :level="selected.risk_level" /></div><SourceBadge :mode="selected.source_mode" :simulated="selected.simulated" /><MediaPanel :asset="asset" :source-mode="selected.source_mode" :simulated="selected.simulated" /><el-timeline v-if="selected.timeline?.length"><el-timeline-item v-for="item in selected.timeline" :key="`${item.time}-${item.title}`" :timestamp="item.time" placement="top"><strong>{{ item.title }}</strong><p>{{ item.detail }}</p></el-timeline-item></el-timeline><el-empty v-else description="当前事件暂无回放时间轴" /></section></template>
  </div>
</template>
