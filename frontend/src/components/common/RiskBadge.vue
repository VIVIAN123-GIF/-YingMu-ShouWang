<script setup>
import { computed } from 'vue'
import { StarFilled } from '@element-plus/icons-vue'
import { RISK_LEVELS } from '../../domain/constants'

const props = defineProps({
  level: { type: String, default: 'GREEN' },
  compact: Boolean,
  textOnly: Boolean,
  score: { type: [Number, String], default: null },
})

const unknownConfig = Object.freeze({ label: '需人工复核', color: '#86909C' })
const config = computed(() => RISK_LEVELS[props.level] || unknownConfig)
const label = computed(() => config.value.label || '需人工复核')
const starCount = computed(() => ({ GREEN: 1, YELLOW: 2, ORANGE: 3, RED: 3 }[props.level] || 0))
const isUnknown = computed(() => !RISK_LEVELS[props.level])
const showScore = computed(() => !isUnknown.value && props.score !== null)
const ariaLabel = computed(() => isUnknown.value
  ? `${label.value}，不可判定`
  : props.textOnly
    ? label.value
  : props.score === null
    ? `${label.value}，${starCount.value}星`
    : `${label.value}，风险分数${props.score}，${starCount.value}星`)
</script>

<template>
  <span class="risk-badge" :class="[`risk-${level.toLowerCase()}`, { compact }]" :aria-label="ariaLabel">
    <span v-if="!textOnly && showScore" class="risk-score">{{ score }}</span>
    <span v-if="!textOnly && !isUnknown && starCount" class="risk-stars" aria-hidden="true">
      <el-icon v-for="index in starCount" :key="index"><StarFilled /></el-icon>
    </span>
    <span class="risk-level-label">{{ label }}</span>
    <span class="sr-only">{{ compact ? config.label : '' }} {{ level === 'YELLOW' ? '建议关注' : '' }} {{ level === 'UNKNOWN' ? '不可判定 人工复核' : '' }}</span>
  </span>
</template>
