<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import flvjs from 'flv.js'
import { Download, Mute, MuteNotification, VideoCamera, VideoCameraFilled, VideoPause, VideoPlay } from '@element-plus/icons-vue'

const props = defineProps({
  available: { type: Boolean, default: false },
  autoStart: { type: Boolean, default: true },
})

const video = ref(null)
const state = ref('idle')
const errorMessage = ref('')
const paused = ref(false)
const muted = ref(true)
const volume = ref(0)
const volumeOpen = ref(false)
const recording = ref(false)
const recordingSupported = ref(false)
let player = null
let recorder = null
let recordingChunks = []
let recordingDownload = false

const playing = computed(() => state.value === 'loading' || state.value === 'playing')

function destroyPlayer() {
  stopRecording(false)
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

function togglePlayback() {
  if (!video.value || state.value !== 'playing') return
  if (video.value.paused) {
    void video.value.play()
    paused.value = false
  } else {
    video.value.pause()
    paused.value = true
  }
}

function toggleMute() {
  if (!video.value) return
  video.value.muted = !video.value.muted
  muted.value = video.value.muted
  if (!muted.value && volume.value === 0) {
    volume.value = 0.8
    video.value.volume = volume.value
  }
}

function setVolume(event) {
  const next = Number(event.target.value)
  volume.value = next
  if (video.value) {
    video.value.volume = next
    video.value.muted = next === 0
    muted.value = video.value.muted
  }
}

function finishRecording(download) {
  recording.value = false
  const chunks = recordingChunks
  recordingChunks = []
  if (download && chunks.length) {
    const blob = new Blob(chunks, { type: recorder?.mimeType || 'video/webm' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `yingmu-live-${new Date().toISOString().replace(/[:.]/g, '-')}.webm`
    link.click()
    URL.revokeObjectURL(url)
  }
}

function stopRecording(download = true) {
  if (!recorder) return
  const current = recorder
  recordingDownload = download
  if (current.state !== 'inactive') {
    current.stop()
  } else {
    finishRecording(download)
    recorder = null
  }
}

function toggleRecording() {
  if (!video.value || state.value !== 'playing') return
  if (recording.value) { stopRecording(true); return }
  if (!recordingSupported.value) {
    errorMessage.value = '当前浏览器不支持直播录制'
    return
  }
  try {
    const stream = video.value.captureStream()
    const mimeType = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm']
      .find((type) => typeof MediaRecorder.isTypeSupported !== 'function' || MediaRecorder.isTypeSupported(type))
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    recordingChunks = []
    recorder.ondataavailable = (event) => { if (event.data.size) recordingChunks.push(event.data) }
    recorder.onstop = () => {
      finishRecording(recordingDownload)
      recorder = null
    }
    recorder.start(1000)
    recording.value = true
  } catch {
    recorder = null
    recording.value = false
    errorMessage.value = '直播录制启动失败，请检查浏览器权限'
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
  paused.value = false
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

watch(() => [props.available, props.autoStart], ([available, autoStart]) => {
  if (available && autoStart && state.value === 'idle' && video.value) void start()
})

onMounted(() => {
  const mediaPrototype = typeof HTMLMediaElement !== 'undefined' ? HTMLMediaElement.prototype : null
  const videoPrototype = typeof HTMLVideoElement !== 'undefined' ? HTMLVideoElement.prototype : null
  recordingSupported.value = typeof MediaRecorder !== 'undefined'
    && (typeof videoPrototype?.captureStream === 'function'
      || typeof mediaPrototype?.captureStream === 'function')
  if (props.available && props.autoStart && state.value === 'idle') void start()
})

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
      <video ref="video" class="live-video" muted autoplay playsinline @playing="state = 'playing'; paused = false" @pause="paused = true" />
      <div v-if="state !== 'playing'" class="live-video-status" role="status">
        <strong v-if="state === 'loading'">正在连接摄像头</strong>
        <strong v-else-if="state === 'failed'">直播暂不可用</strong>
        <strong v-else-if="!available">当前设备或数据模式不支持直播</strong>
        <strong v-else>直播尚未开始</strong>
        <span v-if="errorMessage">{{ errorMessage }}</span>
      </div>
      <div v-if="state === 'playing'" class="live-controls" data-testid="live-controls">
        <button type="button" class="live-control-button" :aria-label="paused ? '继续播放' : '暂停播放'" @click="togglePlayback">
          <el-icon><VideoPlay v-if="paused" /><VideoPause v-else /></el-icon>
        </button>
        <div class="live-volume-control">
          <button type="button" class="live-control-button" :aria-label="muted ? '取消静音并调整音量' : '静音或调整音量'" @click="volumeOpen = !volumeOpen">
            <el-icon><Mute v-if="muted" /><MuteNotification v-else /></el-icon>
          </button>
          <div v-if="volumeOpen" class="live-volume-popover">
            <input class="live-volume" type="range" min="0" max="1" step="0.05" :value="volume" aria-label="音量" @input="setVolume" />
            <output>{{ Math.round(volume * 100) }}</output>
          </div>
        </div>
        <button type="button" class="live-control-button live-record-button" :class="{ active: recording }" :disabled="!recordingSupported" :aria-label="recording ? '停止录制并下载' : '开始录制'" @click="toggleRecording">
          <el-icon><Download v-if="recording" /><VideoCameraFilled v-else /></el-icon>
        </button>
        <span v-if="recording" class="live-recording-label">录制中</span>
      </div>
    </div>
  </section>
</template>
