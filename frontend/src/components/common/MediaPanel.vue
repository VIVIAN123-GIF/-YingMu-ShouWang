<script setup>
import { computed, ref, watch } from 'vue'
import SourceBadge from './SourceBadge.vue'

const props = defineProps({
  asset: { type: Object, default: null },
  sourceMode: { type: String, default: 'MOCK' },
  simulated: { type: Boolean, default: true },
})

const playableUrl = computed(() => props.asset?.stream_url || props.asset?.fallback_url)
const videoError = ref(false)
const videoReady = ref(false)

watch(playableUrl, () => {
  videoError.value = false
  videoReady.value = false
})
</script>

<template>
  <section class="media-card" aria-label="事件画面" data-testid="media-panel">
    <div class="media-toolbar">
      <div>
        <strong>{{ asset?.title || '事件画面' }}</strong>
        <span>{{ asset?.captured_at ? new Date(asset.captured_at).toLocaleString('zh-CN') : '等待授权素材' }}</span>
      </div>
      <SourceBadge :mode="asset?.source_mode || sourceMode" :simulated="asset?.simulated ?? simulated" />
    </div>
    <video
      v-if="playableUrl && !videoError"
      class="event-video"
      controls
      :src="playableUrl"
      data-testid="authorized-video"
      @loadedmetadata="videoReady = true"
      @error="videoError = true"
    >
      当前浏览器不支持视频播放。
    </video>
    <div v-if="videoReady" class="media-verification"><el-tag type="success" size="large">授权片段已加载</el-tag><span>来源：{{ asset?.source_mode }}</span></div>
    <div v-else class="media-placeholder">
      <div class="camera-illustration" aria-hidden="true">
        <span class="camera-lens"></span>
      </div>
      <strong>授权事件片段占位</strong>
      <p v-if="videoError">授权片段加载失败，已停止播放并保留事件信息。</p>
      <p v-else>{{ asset?.notice || '实时画面不可用，页面已切换至授权片段位置。' }}</p>
      <el-tag type="warning" effect="plain" size="large">待素材核验 · 不伪装为实时视频</el-tag>
    </div>
  </section>
</template>
