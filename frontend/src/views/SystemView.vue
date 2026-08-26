<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, CircleClose } from '@element-plus/icons-vue'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import TechnicalDisclosure from '../components/common/TechnicalDisclosure.vue'
import { clearRecordedFeedback, getAllRecordedFeedback, getDeviceStatus } from '../services/repository'

const loading = ref(true)
const error = ref('')
const device = ref(null)
const feedbackRecords = ref([])
async function load() { try { device.value = await getDeviceStatus(); feedbackRecords.value = getAllRecordedFeedback() } catch (err) { error.value = `无法读取设备状态：${err.message}` } finally { loading.value = false } }
function clearFeedback() { clearRecordedFeedback(); feedbackRecords.value = []; ElMessage.success('本地演示记录已清除') }
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="系统和设备状态" description="查看设备是否在线、数据是否持续采集，以及当前能力边界。">
      <SourceBadge v-if="device" :mode="device.source_mode" :simulated="device.simulated" />
    </PageHeader>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="device">
      <section class="content-card system-health-card" data-testid="system-status">
        <div class="system-health-icon" :class="{ offline: !device.online }"><el-icon><component :is="device.online ? CircleCheck : CircleClose" /></el-icon></div>
        <div><span class="section-kicker">当前设备</span><h2>{{ device.online ? '设备连接正常' : '设备当前离线' }}</h2><p>{{ device.collection_active ? '系统正在接收授权范围内的数据。' : '当前没有进行数据采集。' }}</p></div>
        <el-tag :type="device.online ? 'success' : 'danger'" size="large">{{ device.online ? '在线' : '离线' }}</el-tag>
      </section>
      <TechnicalDisclosure title="设备与适配器详情" summary="适配器模式、数据来源、采集状态和设备别名">
        <section class="content-card">
          <dl class="detail-list">
            <div><dt>适配器模式</dt><dd>{{ device.adapter_mode }}</dd></div><div><dt>数据来源</dt><dd>{{ device.source_mode }}</dd></div>
            <div><dt>采集状态</dt><dd>{{ device.collection_active ? '采集运行中' : '采集已停止' }}</dd></div><div><dt>设备别名</dt><dd>{{ device.device_alias }}</dd></div>
          </dl>
          <SourceBadge :mode="device.source_mode" :simulated="device.simulated" />
        </section>
      </TechnicalDisclosure>
      <section class="content-card feedback-audit-card" data-testid="feedback-audit">
        <div class="card-heading"><div><span class="section-kicker">本地演示记录</span><h2>关怀与身份核验</h2></div><el-tag type="warning" effect="plain">{{ feedbackRecords.length }} 条</el-tag></div>
        <div v-if="feedbackRecords.length" class="feedback-record-list">
          <article v-for="record in feedbackRecords.slice().reverse()" :key="record.feedback_id" class="recorded-feedback">
            <strong>{{ record.feedback_kind === 'IDENTITY_VERIFICATION' ? '身份信息核验' : '家属关怀反馈' }}</strong><span>{{ record.value }}</span><small>{{ record.recorded_at }} · {{ record.operator }} · {{ record.event_id }} · {{ record.saved_in_demo ? 'RECORDED_REPLAY 本地演示' : '后端记录' }}</small>
          </article>
        </div>
        <el-empty v-else description="尚未记录关怀反馈或身份核验" />
        <el-button v-if="feedbackRecords.length" plain @click="clearFeedback">清除本地演示记录</el-button>
      </section>
    </template>
  </div>
</template>
