<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import { getLatestForewarning, getSceneCalibration, runtime } from '../services/repository'
import { formatDateTime } from '../utils/format'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const calibration = ref(null)
const associatedForewarning = ref(null)
const error = ref(null)
const sceneConfigId = computed(() => String(route.params.sceneConfigId || ''))
const zoneColors = { HIGH_RISK: '#c94b4b', SUPPORT: '#237451', OBSTACLE: '#d18a2f', SAFE: '#3d7ea6' }
const provenance = computed(() => {
  if (associatedForewarning.value?.scene_config_id === calibration.value?.scene_config_id) return associatedForewarning.value
  if (runtime.activeSource === 'replay_dataset') return { source_mode: 'RECORDED_REPLAY', simulated: true }
  return null
})

function errorState(errorValue) {
  const code = errorValue?.api?.code || 'REQUEST_FAILED'
  const messages = {
    SCENE_CONFIG_MISSING: '场景标定不存在或尚未安装',
    SCENE_CONFIG_INVALID: '场景标定配置非法，无法用于区域判断',
    SCENE_CONFIG_REQUIRED: '缺少场景配置标识',
  }
  return { code, message: messages[code] || errorValue?.api?.message || errorValue?.message || '无法读取场景标定', requestId: errorValue?.api?.request_id || null }
}

function polygonPoints(zone) {
  if (!calibration.value) return ''
  return zone.polygon_norm.map(([x, y]) => `${x * calibration.value.frame_width},${y * calibration.value.frame_height}`).join(' ')
}

function coordinateText(zone) { return zone.polygon_norm.map(([x, y]) => `(${x.toFixed(2)}, ${y.toFixed(2)})`).join(' ') }

async function load() {
  loading.value = true
  error.value = null
  calibration.value = null
  const [calibrationResult, latestResult] = await Promise.allSettled([
    getSceneCalibration(sceneConfigId.value), getLatestForewarning(),
  ])
  if (calibrationResult.status === 'fulfilled') calibration.value = calibrationResult.value
  else error.value = errorState(calibrationResult.reason)
  if (latestResult.status === 'fulfilled') associatedForewarning.value = latestResult.value
  loading.value = false
}

watch(sceneConfigId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="场景标定详情" description="核对固定机位、画面尺寸和归一化区域参数。">
      <SourceBadge v-if="provenance" :mode="provenance.source_mode" :simulated="provenance.simulated" />
      <el-tag v-else type="info" effect="plain" size="large">FastAPI 配置 · 未关联数据来源</el-tag>
    </PageHeader>
    <el-button class="back-button" plain @click="router.push({ name: 'system' })"><el-icon><ArrowLeft /></el-icon>返回系统状态</el-button>
    <el-alert v-if="error" :title="error.message" type="error" :closable="false" show-icon class="calibration-error">
      <template #default><span>错误码：{{ error.code }}</span><span v-if="error.requestId"> · 请求 ID：{{ error.requestId }}</span></template>
    </el-alert>

    <template v-if="calibration">
      <section class="calibration-summary-band" data-testid="calibration-summary">
        <dl class="detail-list">
          <div><dt>契约版本</dt><dd>{{ calibration.schema_version }}</dd></div><div><dt>配置标识</dt><dd>{{ calibration.scene_config_id }}</dd></div>
          <div><dt>摄像机位置</dt><dd>{{ calibration.camera_position_id }}</dd></div><div><dt>场景位置</dt><dd>{{ calibration.location }}</dd></div>
          <div><dt>画面尺寸</dt><dd>{{ calibration.frame_width }} × {{ calibration.frame_height }}</dd></div><div><dt>生效时间</dt><dd>{{ formatDateTime(calibration.effective_from) }}</dd></div>
          <div><dt>替代版本</dt><dd>{{ calibration.supersedes || '无' }}</dd></div><div><dt>区域数量</dt><dd>{{ calibration.zones.length }}</dd></div>
        </dl>
      </section>

      <section class="calibration-workspace">
        <div class="calibration-preview-wrap">
          <div class="card-heading"><div><span class="section-kicker">区域预览</span><h2>归一化画面坐标</h2></div></div>
          <svg class="calibration-preview" :viewBox="`0 0 ${calibration.frame_width} ${calibration.frame_height}`" role="img" aria-label="场景标定区域预览">
            <rect width="100%" height="100%" fill="#edf2f0" />
            <g v-for="zone in calibration.zones" :key="zone.zone_id">
              <polygon :points="polygonPoints(zone)" :fill="zoneColors[zone.zone_type]" fill-opacity="0.24" :stroke="zoneColors[zone.zone_type]" :stroke-width="Math.max(calibration.frame_width / 320, 2)" />
              <text :x="zone.polygon_norm[0][0] * calibration.frame_width" :y="zone.polygon_norm[0][1] * calibration.frame_height - 8" :font-size="Math.max(calibration.frame_width / 55, 14)" :fill="zoneColors[zone.zone_type]">{{ zone.zone_id }}</text>
            </g>
          </svg>
          <div class="calibration-legend"><span v-for="(color, type) in zoneColors" :key="type"><i :style="{ backgroundColor: color }" />{{ type }}</span></div>
        </div>

        <div class="calibration-zone-table">
          <div class="card-heading"><div><span class="section-kicker">区域参数</span><h2>区域边界</h2></div></div>
          <el-table :data="calibration.zones" max-height="430" empty-text="未配置区域">
            <el-table-column prop="zone_id" label="区域标识" min-width="150" />
            <el-table-column prop="zone_type" label="类型" width="120" />
            <el-table-column label="归一化坐标" min-width="260"><template #default="{ row }"><span class="coordinate-text">{{ coordinateText(row) }}</span></template></el-table-column>
          </el-table>
        </div>
      </section>
      <el-alert v-if="calibration.notes" :title="calibration.notes" type="info" :closable="false" show-icon />
    </template>
  </div>
</template>
