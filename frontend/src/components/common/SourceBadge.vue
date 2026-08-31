<script setup>
import { computed } from 'vue'
import { SOURCE_MODES } from '../../domain/constants'

const props = defineProps({
  mode: { type: String, default: 'RECORDED_REPLAY' },
  simulated: { type: Boolean, default: false },
  button: Boolean,
})

const config = computed(() => SOURCE_MODES[props.mode] || { label: props.mode, tone: 'info' })
</script>

<template>
  <span class="source-wrap" :class="{ 'source-wrap-button': button }">
    <el-button v-if="button" class="source-badge-button" type="primary" plain>{{ config.label }}</el-button>
    <el-tag v-else-if="!simulated" class="source-badge" :type="config.tone" effect="plain" size="large">
      {{ config.label }}
    </el-tag>
    <span v-else-if="simulated" class="simulation-mark">授权回放</span>
    <span class="sr-only">{{ config.label }}</span>
  </span>
</template>
