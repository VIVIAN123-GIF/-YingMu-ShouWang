<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Camera, CircleCheck, CircleClose, Location, VideoPause } from '@element-plus/icons-vue'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import PrivateImage from '../components/common/PrivateImage.vue'
import LiveVideoPanel from '../components/common/LiveVideoPanel.vue'
import {
  clearRecordedFeedback, getFeedbackAuditRecords,
  createDeviceSnapshot, getCurrentSceneCalibration, getDeviceSnapshot, getDeviceStatus, getLatestForewarning,
  runtime, stopDeviceCollection,
} from '../services/repository'
import { deviceAliasLabel, deviceReferenceLabel, displayValueLabel, errorCodeLabel, eventIdentifierLabel, feedbackTone, formatDateTime, sceneConfigLabel } from '../utils/format'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const device = ref(null)
const latestForewarning = ref(null)
const currentCalibration = ref(null)
const feedbackRecords = ref([])
const feedbackClearNotice = ref('')
const feedbackClearDialogOpen = ref(false)
const snapshot = ref(null)
const snapshotLoading = ref(false)
const snapshotError = ref(null)
const snapshotAsset = ref(null)
const snapshotHistorical = ref(false)
const autoCaptureStarted = ref(false)
const stopDialogOpen = ref(false)
const stopLoading = ref(false)
const controlToken = ref('')
const controlError = ref(null)
const SYSTEM_POLL_MS = 2000
let systemPollTimer = null
let systemPollInFlight = false
let systemPollingActive = false

const sceneConfigId = computed(() => currentCalibration.value?.scene_config_id || latestForewarning.value?.scene_config_id || '')
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
  const [deviceResult, forewarningResult, calibrationResult] = await Promise.allSettled([
    getDeviceStatus(), getLatestForewarning(), getCurrentSceneCalibration(),
  ])
  if (deviceResult.status === 'fulfilled') device.value = deviceResult.value
  else error.value = `无法读取设备状态：${deviceResult.reason.message}`
  if (forewarningResult.status === 'fulfilled') latestForewarning.value = forewarningResult.value
  if (calibrationResult.status === 'fulfilled') currentCalibration.value = calibrationResult.value
  feedbackRecords.value = await getFeedbackAuditRecords()
  loading.value = false
  if (liveAvailable.value) void autoInitializeMedia()
  else {
    try {
      snapshot.value = await getDeviceSnapshot()
      snapshotHistorical.value = true
    } catch { /* The structured status below remains available. */ }
  }
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
    snapshotHistorical.value = false
  }
  catch (errorValue) {
    snapshotError.value = apiError(errorValue, '设备快照暂不可用')
    try {
      snapshot.value = await getDeviceSnapshot()
      snapshotAsset.value = null
      snapshotHistorical.value = true
    } catch { snapshot.value = null }
  }
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
function clearFeedback() {
  clearRecordedFeedback()
  feedbackRecords.value = []
  feedbackClearDialogOpen.value = false
  feedbackClearNotice.value = '本页记录已清除。数据库审计记录未删除，重新进入页面后仍可查看。'
  ElMessage.success('本页反馈记录已清除')
}

function stopSystemPolling() {
  if (systemPollTimer !== null) window.clearTimeout(systemPollTimer)
  systemPollTimer = null
}

function scheduleSystemPolling() {
  stopSystemPolling()
  if (!systemPollingActive || runtime.mode === 'replay') return
  systemPollTimer = window.setTimeout(async () => {
    systemPollTimer = null
    if (systemPollInFlight) { scheduleSystemPolling(); return }
    systemPollInFlight = true
    try {
      const [deviceResult, forewarningResult] = await Promise.allSettled([
        getDeviceStatus(), getLatestForewarning(),
      ])
      if (deviceResult.status === 'fulfilled') { device.value = deviceResult.value; error.value = '' }
      else error.value = `无法读取设备状态：${deviceResult.reason.message}`
      if (forewarningResult.status === 'fulfilled') latestForewarning.value = forewarningResult.value
    } finally {
      systemPollInFlight = false
      scheduleSystemPolling()
    }
  }, SYSTEM_POLL_MS)
}
function openCalibration() { if (sceneConfigId.value) router.push({ name: 'scene-calibration', params: { sceneConfigId: sceneConfigId.value } }) }
onMounted(async () => { systemPollingActive = true; await load(); scheduleSystemPolling() })
watch(() => runtime.mode, scheduleSystemPolling)
onBeforeUnmount(() => { systemPollingActive = false; stopSystemPolling() })
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
        <section
          class="content-card snapshot-card"
          :class="{
            'snapshot-card-empty': !snapshot && !snapshotError && !snapshotLoading,
            'snapshot-card-pending': !snapshot && snapshotLoading,
          }"
          data-testid="device-snapshot"
        >
          <div class="card-heading"><div><span class="section-kicker">设备快照</span><h2>最近一次主动抓拍</h2></div><el-button :loading="snapshotLoading" type="primary" @click="captureSnapshot"><el-icon><Camera /></el-icon>获取快照</el-button></div>
          <el-alert v-if="snapshotError" :title="snapshotHistorical ? `${snapshotError.message}，下方显示最近可用记录` : snapshotError.message" type="warning" :closable="false" show-icon>
            <template #default><span>错误类型：{{ errorCodeLabel(snapshotError.code) }}</span><span v-if="snapshotError.requestId"> · 请求编号：{{ snapshotError.requestId }}</span></template>
          </el-alert>
          <div v-if="snapshot" class="snapshot-result">
            <PrivateImage v-if="snapshotAsset?.asset_id" :asset-id="snapshotAsset.asset_id" alt="授权主动抓拍" />
            <div class="snapshot-unavailable"><el-icon><Camera /></el-icon><div><strong>{{ snapshotHistorical ? '最近可用快照记录' : '抓拍已完成' }}</strong><span>{{ snapshotHistorical ? '历史元数据，不代表本次实时抓拍成功' : '本次抓拍结果已进入受控素材链路' }}</span></div></div>
            <dl class="detail-list compact-detail-list">
              <div><dt>抓拍时间</dt><dd>{{ formatDateTime(snapshot.captured_at) }}</dd></div><div><dt>设备引用</dt><dd>{{ deviceReferenceLabel(snapshot.device_ref) }}</dd></div>
              <div><dt>来源模式</dt><dd>{{ displayValueLabel(snapshot.source_mode) }}</dd></div><div><dt>处理耗时</dt><dd>{{ snapshot.provider_latency_ms ?? 0 }} 毫秒</dd></div>
            </dl>
            <SourceBadge :mode="snapshot.source_mode" :simulated="snapshot.simulated" />
          </div>
          <div v-else-if="snapshotLoading" class="snapshot-pending" role="status" aria-live="polite">
            <span class="snapshot-pending-spinner" aria-hidden="true"></span>
            <div><strong>正在获取主动抓拍</strong><span>完成后将在此处显示本次抓拍结果</span></div>
          </div>
          <div v-else class="snapshot-unavailable"><el-icon><Camera /></el-icon><div><strong>等待首次快照记录</strong><span>设备状态与采集链路仍可在本页核验</span></div></div>
        </section>

        <div class="system-side-stack">
          <section class="content-card scene-link-card" data-testid="scene-calibration-link">
            <div class="card-heading"><div><span class="section-kicker">场景配置</span><h2>当前关联标定</h2></div><el-icon class="card-heading-icon"><Location /></el-icon></div>
            <template v-if="sceneConfigId">
              <dl class="detail-list compact-detail-list"><div><dt>配置标识</dt><dd>{{ sceneConfigLabel(sceneConfigId) }}</dd></div><div><dt>生效时间</dt><dd>{{ currentCalibration ? formatDateTime(currentCalibration.effective_from) : formatDateTime(latestForewarning.evaluated_at) }}</dd></div></dl>
              <SourceBadge v-if="latestForewarning" :mode="latestForewarning.source_mode" :simulated="latestForewarning.simulated" />
              <el-button plain @click="openCalibration">查看场景标定</el-button>
            </template>
            <el-empty v-else description="最新预警未关联场景标定" :image-size="72" />
          </section>

          <section class="content-card adapter-mode-card" data-testid="adapter-mode">
            <div class="card-heading"><div><span class="section-kicker">设备接入</span><h2>适配器模式</h2></div></div>
            <dl class="detail-list compact-detail-list">
              <div><dt>适配器模式</dt><dd>{{ displayValueLabel(device.adapter_mode) }}</dd></div><div><dt>数据来源</dt><dd>{{ displayValueLabel(device.source_mode) }}</dd></div>
              <div><dt>采集状态</dt><dd>{{ device.collection_active ? '采集运行中' : '采集已停止' }}</dd></div><div><dt>设备别名</dt><dd>{{ deviceAliasLabel(device.device_alias) }}</dd></div>
            </dl>
            <div class="technical-device-actions">
              <SourceBadge :mode="device.source_mode" :simulated="device.simulated" />
              <el-button type="danger" plain :disabled="!controlAvailable" data-testid="stop-collection" @click="stopDialogOpen = true"><el-icon><VideoPause /></el-icon>停止采集</el-button>
            </div>
            <el-alert v-if="!controlAvailable && device.collection_active" title="回放或降级来源不能执行设备控制" type="warning" :closable="false" show-icon />
          </section>
        </div>
      </div>

      <section class="content-card feedback-audit-card" data-testid="feedback-audit">
        <div class="card-heading"><div><span class="section-kicker">反馈记录</span><h2>关怀与身份核验</h2></div><el-tag type="warning" effect="plain">{{ feedbackRecords.length }} 条</el-tag></div>
        <el-alert v-if="feedbackClearNotice" data-testid="feedback-clear-notice" :title="feedbackClearNotice" type="success" :closable="false" show-icon />
        <div v-if="feedbackRecords.length" class="feedback-record-list">
          <article v-for="record in feedbackRecords.slice().reverse()" :key="record.feedback_id" class="recorded-feedback" :class="`feedback-${feedbackTone(record.value)}`">
            <strong>{{ record.feedback_kind === 'IDENTITY_VERIFICATION' ? '身份信息核验' : '家属关怀反馈' }}</strong><span>{{ record.value }}</span><small>{{ record.recorded_at }} · {{ displayValueLabel(record.operator) }} · {{ eventIdentifierLabel(record.event_id) }}</small>
          </article>
        </div>
        <el-empty v-else description="尚未记录关怀反馈或身份核验" />
        <el-button v-if="feedbackRecords.length" data-testid="clear-feedback" plain @click="feedbackClearDialogOpen = true">清除本页记录</el-button>
      </section>
    </template>

    <el-dialog v-model="feedbackClearDialogOpen" title="确认清除记录" width="min(92vw, 440px)" destroy-on-close>
      <el-alert title="确认清除本页显示的反馈记录吗？" type="warning" :closable="false" show-icon>
        <template #default>数据库审计记录不会被删除，重新进入页面后仍可查看。</template>
      </el-alert>
      <template #footer>
        <el-button data-testid="clear-feedback-cancel" @click="feedbackClearDialogOpen = false">取消</el-button>
        <el-button type="danger" data-testid="clear-feedback-confirm" @click="clearFeedback">确认清除</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="stopDialogOpen" title="确认停止采集" width="min(92vw, 480px)" destroy-on-close @closed="closeStopDialog">
      <el-alert title="停止后设备将不再向系统提供新的采集数据" type="warning" :closable="false" show-icon />
      <el-form label-position="top" class="control-token-form" @submit.prevent="confirmStop">
        <el-form-item label="现场控制令牌"><el-input v-model="controlToken" type="password" show-password autocomplete="off" data-testid="control-token" /></el-form-item>
      </el-form>
      <el-alert v-if="controlError" :title="controlError.message" type="error" :closable="false" show-icon>
        <template #default><span>错误类型：{{ errorCodeLabel(controlError.code) }}</span><span v-if="controlError.requestId"> · 请求编号：{{ controlError.requestId }}</span></template>
      </el-alert>
      <template #footer><el-button @click="stopDialogOpen = false">取消</el-button><el-button type="danger" :disabled="!controlToken" :loading="stopLoading" @click="confirmStop">确认停止</el-button></template>
    </el-dialog>
  </div>
</template>
