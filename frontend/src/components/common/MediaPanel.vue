<script setup>
import { computed, ref, watch } from 'vue'
import SourceBadge from './SourceBadge.vue'
import { formatDateTime, mediaNoticeLabel, mediaTitleLabel } from '../../utils/format'

const props = defineProps({
  asset: { type: Object, default: null },
  sourceMode: { type: String, default: 'RECORDED_REPLAY' },
  simulated: { type: Boolean, default: true },
})

const playableUrl = computed(() => props.asset?.stream_url || props.asset?.fallback_url)
const shouldAutoplay = computed(() => (
  (props.asset?.source_mode || props.sourceMode) === 'RECORDED_REPLAY'
  && (props.asset?.simulated ?? props.simulated) === true
))
const activeUrl = ref('')
const videoError = ref(false)
const videoReady = ref(false)
const videoAspectRatio = ref('')
const fallbackAttempted = ref(false)

function resetVideoState() {
  activeUrl.value = playableUrl.value || ''
  videoError.value = false
  videoReady.value = false
  videoAspectRatio.value = ''
  fallbackAttempted.value = false
}

watch(playableUrl, resetVideoState, { immediate: true })

function handleMetadata(event) {
  const { videoWidth, videoHeight } = event.target
  if (videoWidth > 0 && videoHeight > 0) videoAspectRatio.value = `${videoWidth} / ${videoHeight}`
  if (event.target.duration > 0 && event.target.currentTime === 0) {
    event.target.currentTime = Math.min(0.05, event.target.duration / 100)
  }
}

function handleLoadedData() {
  videoReady.value = true
}

function handleError() {
  const fallbackUrl = props.asset?.fallback_url
  if (!fallbackAttempted.value && fallbackUrl && activeUrl.value !== fallbackUrl) {
    fallbackAttempted.value = true
    activeUrl.value = fallbackUrl
    videoError.value = false
    videoReady.value = false
    videoAspectRatio.value = ''
    return
  }
  videoError.value = true
  videoReady.value = false
}
</script>

<template>
  <section class="media-card" aria-label="事件画面" data-testid="media-panel">
    <div class="media-toolbar">
      <div>
        <strong>{{ mediaTitleLabel(asset?.title) }}</strong>
        <span>{{ asset?.captured_at ? formatDateTime(asset.captured_at) : '等待授权素材' }}</span>
      </div>
      <SourceBadge button :mode="asset?.source_mode || sourceMode" :simulated="asset?.simulated ?? simulated" />
    </div>
    <div v-if="activeUrl && !videoError" class="media-video-frame" :data-aspect-ratio="videoAspectRatio || undefined">
      <video
        class="event-video"
        controls
        preload="auto"
        playsinline
        :autoplay="shouldAutoplay"
        :muted="shouldAutoplay"
        :style="videoAspectRatio ? { aspectRatio: videoAspectRatio } : undefined"
        :src="activeUrl"
        data-testid="authorized-video"
        @loadedmetadata="handleMetadata"
        @loadeddata="handleLoadedData"
        @error="handleError"
      >
        当前浏览器不支持视频播放。
      </video>
    </div>
    <div v-if="videoReady" class="media-verification"><el-tag type="success" size="large">授权片段已加载</el-tag><span>来源：授权回放</span></div>
    <div v-else class="media-placeholder">
      <div class="camera-illustration" aria-hidden="true">
        <span class="camera-lens"></span>
      </div>
      <strong>授权事件片段占位</strong>
      <p v-if="videoError">授权片段加载失败，已停止播放并保留事件信息。</p>
      <p v-else>{{ mediaNoticeLabel(asset?.notice) || '实时画面不可用，页面已切换至授权片段位置。' }}</p>
      <span class="media-placeholder-status" role="status">待素材核验 · 不伪装为实时视频</span>
    </div>
  </section>
</template>
