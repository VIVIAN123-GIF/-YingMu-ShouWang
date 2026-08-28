<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import flvjs from 'flv.js'
import { VideoCamera, VideoPause } from '@element-plus/icons-vue'

const props = defineProps({
  available: { type: Boolean, default: false },
})

const video = ref(null)
const state = ref('idle')
const errorMessage = ref('')
let player = null

const playing = computed(() => state.value === 'loading' || state.value === 'playing')

function destroyPlayer() {
  if (player) {
    player.pause()
    player.unload()
    player.detachMediaElement()
    player.destroy()
    player = null
  }
  if (video.value) {
    video.value.removeAttribute('src')
    // jsdom logs a virtual-console warning for the unimplemented media loader.
    if (!navigator.userAgent.toLowerCase().includes('jsdom')) {
      try { video.value.load() } catch { /* Some browsers may not implement load. */ }
    }
  }
}

function stop() {
  destroyPlayer()
  state.value = 'stopped'
  errorMessage.value = ''
}

async function start() {
  if (!props.available || playing.value) return
  destroyPlayer()
  errorMessage.value = ''
  if (!flvjs.isSupported()) {
    state.value = 'failed'
    errorMessage.value = '当前浏览器不支持 HTTP-FLV 直播播放'
    return
  }
  state.value = 'loading'
  player = flvjs.createPlayer({ type: 'flv', isLive: true, url: '/media/live', withCredentials: true }, {
    enableStashBuffer: false,
    stashInitialSize: 128,
    lazyLoad: false,
  })
  player.attachMediaElement(video.value)
  player.on(flvjs.Events.ERROR, () => {
    destroyPlayer()
    state.value = 'failed'
    errorMessage.value = '直播连接已中断，请重新连接'
  })
  try {
    player.load()
    await player.play()
    state.value = 'playing'
  } catch {
    destroyPlayer()
    state.value = 'failed'
    errorMessage.value = '直播加载失败，请确认登录会话、设备状态和直播配置'
  }
}

onBeforeUnmount(destroyPlayer)
</script>

<template>
  <section class="content-card live-card" data-testid="device-live">
    <div class="card-heading">
      <div><span class="section-kicker">实时画面</span><h2>摄像头直播</h2></div>
      <div class="live-actions">
        <el-button v-if="!playing" type="primary" :disabled="!available" @click="start"><el-icon><VideoCamera /></el-icon>开始直播</el-button>
        <el-button v-else type="danger" plain @click="stop"><el-icon><VideoPause /></el-icon>停止直播</el-button>
      </div>
    </div>
    <div class="live-video-frame">
      <video ref="video" class="live-video" muted controls autoplay playsinline @playing="state = 'playing'" />
      <div v-if="state !== 'playing'" class="live-video-status" role="status">
        <strong v-if="state === 'loading'">正在连接摄像头</strong>
        <strong v-else-if="state === 'failed'">直播暂不可用</strong>
        <strong v-else-if="!available">当前设备或数据模式不支持直播</strong>
        <strong v-else>直播尚未开始</strong>
        <span v-if="errorMessage">{{ errorMessage }}</span>
      </div>
    </div>
  </section>
</template>
