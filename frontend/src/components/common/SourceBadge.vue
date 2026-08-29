<script setup>
import { computed } from 'vue'
import { SOURCE_MODES } from '../../domain/constants'

const props = defineProps({
  mode: { type: String, default: 'RECORDED_REPLAY' },
  simulated: { type: Boolean, default: false },
})

const config = computed(() => SOURCE_MODES[props.mode] || { label: props.mode, tone: 'info' })
</script>

<template>
  <span class="source-wrap">
    <el-tag v-if="!simulated" class="source-badge" :type="config.tone" effect="plain" size="large">
      {{ config.label }}
    </el-tag>
    <span v-if="simulated" class="simulation-mark">授权回放</span>
    <span class="sr-only">{{ mode }} 模拟实验回放</span>
  </span>
</template>
