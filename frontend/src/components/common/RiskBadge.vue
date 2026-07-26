<script setup>
import { computed } from 'vue'
import { RISK_LEVELS } from '../../domain/constants'

const props = defineProps({
  level: { type: String, default: 'GREEN' },
  compact: Boolean,
})

const config = computed(() => RISK_LEVELS[props.level] || RISK_LEVELS.GREEN)
</script>

<template>
  <span class="risk-badge" :class="[`risk-${level.toLowerCase()}`, { compact }]">
    <span class="risk-dot" aria-hidden="true"></span>
    <span>{{ compact ? level : config.label }}</span>
  </span>
</template>
