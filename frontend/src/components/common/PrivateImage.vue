<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { getPrivateAssetBlob } from '../../services/repository'

const props = defineProps({
  assetId: { type: String, default: '' },
  alt: { type: String, default: '授权抓拍图片' },
})

const emit = defineEmits(['state'])
const objectUrl = ref('')
const state = ref('idle')
const message = ref('')
let requestSerial = 0

function revokeUrl() {
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
  objectUrl.value = ''
}

async function load() {
  const serial = ++requestSerial
  revokeUrl()
  message.value = ''
  if (!props.assetId) { state.value = 'idle'; emit('state', state.value); return }
  state.value = 'loading'; emit('state', state.value)
  try {
    const blob = await getPrivateAssetBlob(props.assetId)
    if (serial !== requestSerial) return
    objectUrl.value = URL.createObjectURL(blob)
    state.value = 'ready'
  } catch (error) {
    if (serial !== requestSerial) return
    state.value = 'failed'
    message.value = error?.api?.message || error?.message || '授权抓拍加载失败'
  }
  emit('state', state.value, message.value)
}

watch(() => props.assetId, load, { immediate: true })
onBeforeUnmount(() => { requestSerial += 1; revokeUrl() })
</script>

<template>
  <div class="private-image" data-testid="private-image">
    <div v-if="state === 'loading'" class="media-placeholder"><strong>正在加载授权抓拍</strong></div>
    <img v-else-if="state === 'ready'" :src="objectUrl" :alt="alt" class="private-image-content" />
    <div v-else-if="state === 'failed'" class="media-placeholder" role="alert"><strong>授权抓拍不可用</strong><p>{{ message }}</p></div>
    <div v-else class="media-placeholder"><strong>等待授权抓拍</strong></div>
  </div>
</template>
