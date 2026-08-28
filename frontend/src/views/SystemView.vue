<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Camera, CircleCheck, CircleClose, Location, VideoPause } from '@element-plus/icons-vue'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import PrivateImage from '../components/common/PrivateImage.vue'
import LiveVideoPanel from '../components/common/LiveVideoPanel.vue'
import TechnicalDisclosure from '../components/common/TechnicalDisclosure.vue'
import {
  clearRecordedFeedback, getAllRecordedFeedback,
  createDeviceSnapshot, getDeviceSnapshot, getDeviceStatus, getLatestForewarning,
  runtime, stopDeviceCollection,
} from '../services/repository'
import { useViewMode } from '../services/viewMode'
import { feedbackTone, formatDateTime } from '../utils/format'

const router = useRouter()
const { isReview } = useViewMode()
const loading = ref(true)
const error = ref('')
const device = ref(null)
const latestForewarning = ref(null)
const feedbackRecords = ref([])
const snapshot = ref(null)
const snapshotLoading = ref(false)
const snapshotError = ref(null)
const snapshotAsset = ref(null)
const autoCaptureStarted = ref(false)
const stopDialogOpen = ref(false)
const stopLoading = ref(false)
const controlToken = ref('')
const controlError = ref(null)

const sceneConfigId = computed(() => latestForewarning.value?.scene_config_id || '')
const controlAvailable = computed(() => (
  device.value?.collection_active
  && device.value?.source_mode === 'LIVE_DEVICE'
  && !device.value?.simulated
  && runtime.mode !== 'replay'
))
const liveAvailable = computed(() => (
  device.value?.online
  && device.value?.collection_active
  && device.value?.source_mode === 'LIVE_DEVICE'
  && !device.value?.simulated
  && runtime.mode !== 'replay'
))

function apiError(errorValue, fallback) {
  return {
    message: errorValue?.api?.message || errorValue?.message || fallback,
    code: errorValue?.api?.code || 'REQUEST_FAILED',
    requestId: errorValue?.api?.request_id || null,
  }
}

async function load() {
  const [deviceResult, forewarningResult] = await Promise.allSettled([getDeviceStatus(), getLatestForewarning()])
  if (deviceResult.status === 'fulfilled') device.value = deviceResult.value
  else error.value = `无法读取设备状态：${deviceResult.reason.message}`
  if (forewarningResult.status === 'fulfilled') latestForewarning.value = forewarningResult.value
  feedbackRecords.value = getAllRecordedFeedback()
  loading.value = false
  void autoInitializeMedia()
}

async function captureSnapshot() {
  if (snapshotLoading.value) return
  snapshotLoading.value = true
  snapshotError.value = null
  try {
    // Keep the legacy GET fixture usable in isolated UI tests and replay-only builds.
    const capture = createDeviceSnapshot || getDeviceSnapshot
    snapshotAsset.value = await capture()
    snapshot.value = snapshotAsset.value
  }
  catch (errorValue) { snapshot.value = null; snapshotError.value = apiError(errorValue, '设备快照暂不可用') }
  finally { snapshotLoading.value = false }
}

async function autoInitializeMedia() {
  if (!device.value || !liveAvailable.value || autoCaptureStarted.value) return
  autoCaptureStarted.value = true
  await captureSnapshot()
}

async function confirmStop() {
  if (!controlToken.value || stopLoading.value) return
  stopLoading.value = true
  controlError.value = null
  try {
    const result = await stopDeviceCollection(controlToken.value)
    device.value = { ...device.value, ...result, online: result.online ?? device.value?.online }
    stopDialogOpen.value = false
    ElMessage.success('采集已停止')
  } catch (errorValue) {
    controlError.value = apiError(errorValue, '停止采集失败')
  } finally {
    controlToken.value = ''
    stopLoading.value = false
  }
}

function closeStopDialog() { controlToken.value = ''; controlError.value = null }
function clearFeedback() { clearRecordedFeedback(); feedbackRecords.value = []; ElMessage.success('本地演示记录已清除') }
function openCalibration() { if (sceneConfigId.value) router.push({ name: 'scene-calibration', params: { sceneConfigId: sceneConfigId.value } }) }
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="系统和设备状态" description="查看设备在线、采集、快照和当前场景配置状态。">
      <SourceBadge v-if="device" :mode="device.source_mode" :simulated="device.simulated" />
    </PageHeader>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="device">
      <section class="content-card system-health-card" data-testid="system-status">
        <div class="system-health-icon" :class="{ offline: !device.online }"><el-icon><component :is="device.online ? CircleCheck : CircleClose" /></el-icon></div>
        <div><span class="section-kicker">当前设备</span><h2>{{ device.online ? '设备连接正常' : '设备当前离线' }}</h2><p>{{ device.collection_active ? '系统正在接收授权范围内的数据。' : '当前没有进行数据采集。' }}</p></div>
        <el-tag :type="device.online ? 'success' : 'danger'" size="large">{{ device.online ? '在线' : '离线' }}</el-tag>
      </section>

      <LiveVideoPanel :available="liveAvailable" auto-start />

      <div class="system-operations-grid">
        <section class="content-card snapshot-card" data-testid="device-snapshot">
          <div class="card-heading"><div><span class="section-kicker">设备快照</span><h2>最近一次主动抓拍</h2></div><el-button :loading="snapshotLoading" type="primary" @click="captureSnapshot"><el-icon><Camera /></el-icon>获取快照</el-button></div>
          <el-alert v-if="snapshotError" :title="snapshotError.message" type="error" :closable="false" show-icon>
            <template #default><span>错误码：{{ snapshotError.code }}</span><span v-if="snapshotError.requestId"> · 请求 ID：{{ snapshotError.requestId }}</span></template>
          </el-alert>
          <div v-else-if="snapshot" class="snapshot-result">
            <PrivateImage :asset-id="snapshotAsset?.asset_id" alt="授权主动抓拍" />
            <div class="snapshot-unavailable"><el-icon><Camera /></el-icon><strong>抓拍已完成</strong></div>
            <dl class="detail-list compact-detail-list">
              <div><dt>抓拍时间</dt><dd>{{ formatDateTime(snapshot.captured_at) }}</dd></div><div><dt>设备引用</dt><dd>{{ snapshot.device_ref }}</dd></div>
              <div><dt>素材类型</dt><dd>{{ snapshot.content_type }}</dd></div><div><dt>素材大小</dt><dd>{{ snapshot.byte_size }} bytes</dd></div>
            </dl>
            <SourceBadge :mode="snapshot.source_mode" :simulated="snapshot.simulated" />
          </div>
          <el-empty v-else description="尚未获取设备快照" :image-size="72" />
        </section>

        <section class="content-card scene-link-card" data-testid="scene-calibration-link">
          <div class="card-heading"><div><span class="section-kicker">场景配置</span><h2>当前关联标定</h2></div><el-icon class="card-heading-icon"><Location /></el-icon></div>
          <template v-if="sceneConfigId">
            <dl class="detail-list compact-detail-list"><div><dt>配置标识</dt><dd>{{ sceneConfigId }}</dd></div><div><dt>关联时间</dt><dd>{{ formatDateTime(latestForewarning.evaluated_at) }}</dd></div></dl>
            <SourceBadge :mode="latestForewarning.source_mode" :simulated="latestForewarning.simulated" />
            <el-button plain @click="openCalibration">查看场景标定</el-button>
          </template>
          <el-empty v-else description="最新预警未关联场景标定" :image-size="72" />
        </section>
      </div>

      <TechnicalDisclosure title="设备与适配器详情" summary="适配器模式、数据来源、采集状态和设备别名">
        <section class="content-card">
          <dl class="detail-list">
            <div><dt>适配器模式</dt><dd>{{ device.adapter_mode }}</dd></div><div><dt>数据来源</dt><dd>{{ device.source_mode }}</dd></div>
            <div><dt>采集状态</dt><dd>{{ device.collection_active ? '采集运行中' : '采集已停止' }}</dd></div><div><dt>设备别名</dt><dd>{{ device.device_alias }}</dd></div>
          </dl>
          <div class="technical-device-actions">
            <SourceBadge :mode="device.source_mode" :simulated="device.simulated" />
            <el-button v-if="isReview" type="danger" plain :disabled="!controlAvailable" data-testid="stop-collection" @click="stopDialogOpen = true"><el-icon><VideoPause /></el-icon>停止采集</el-button>
          </div>
          <el-alert v-if="isReview && !controlAvailable && device.collection_active" title="回放或降级来源不能执行设备控制" type="warning" :closable="false" show-icon />
        </section>
      </TechnicalDisclosure>

      <section class="content-card feedback-audit-card" data-testid="feedback-audit">
        <div class="card-heading"><div><span class="section-kicker">本地演示记录</span><h2>关怀与身份核验</h2></div><el-tag type="warning" effect="plain">{{ feedbackRecords.length }} 条</el-tag></div>
        <div v-if="feedbackRecords.length" class="feedback-record-list">
          <article v-for="record in feedbackRecords.slice().reverse()" :key="record.feedback_id" class="recorded-feedback" :class="`feedback-${feedbackTone(record.value)}`">
            <strong>{{ record.feedback_kind === 'IDENTITY_VERIFICATION' ? '身份信息核验' : '家属关怀反馈' }}</strong><span>{{ record.value }}</span><small>{{ record.recorded_at }} · {{ record.operator }} · {{ record.event_id }} · {{ record.saved_in_demo ? 'RECORDED_REPLAY 本地演示' : '后端记录' }}</small>
          </article>
        </div>
        <el-empty v-else description="尚未记录关怀反馈或身份核验" />
        <el-button v-if="feedbackRecords.length" plain @click="clearFeedback">清除本地演示记录</el-button>
      </section>
    </template>

    <el-dialog v-model="stopDialogOpen" title="确认停止采集" width="min(92vw, 480px)" destroy-on-close @closed="closeStopDialog">
      <el-alert title="停止后设备将不再向系统提供新的采集数据" type="warning" :closable="false" show-icon />
      <el-form label-position="top" class="control-token-form" @submit.prevent="confirmStop">
        <el-form-item label="现场控制令牌"><el-input v-model="controlToken" type="password" show-password autocomplete="off" data-testid="control-token" /></el-form-item>
      </el-form>
      <el-alert v-if="controlError" :title="controlError.message" type="error" :closable="false" show-icon>
        <template #default><span>错误码：{{ controlError.code }}</span><span v-if="controlError.requestId"> · 请求 ID：{{ controlError.requestId }}</span></template>
      </el-alert>
      <template #footer><el-button @click="stopDialogOpen = false">取消</el-button><el-button type="danger" :disabled="!controlToken" :loading="stopLoading" @click="confirmStop">确认停止</el-button></template>
    </el-dialog>
  </div>
</template>
