<script setup>
import { computed } from 'vue'
import { CircleCheckFilled, CircleCloseFilled, WarnTriangleFilled, WarningFilled } from '@element-plus/icons-vue'
import { RISK_LEVELS } from '../../domain/constants'

const props = defineProps({
  level: { type: String, default: 'GREEN' },
  compact: Boolean,
  score: { type: [Number, String], default: null },
})

const unknownConfig = Object.freeze({ label: '需人工复核', color: '#6B7280', icon: 'WarningFilled' })
const config = computed(() => RISK_LEVELS[props.level] || unknownConfig)
const iconMap = { CircleCheckFilled, WarningFilled, WarnTriangleFilled, CircleCloseFilled }
const icon = computed(() => iconMap[config.value.icon] || WarningFilled)
const label = computed(() => config.value.label || '需人工复核')
</script>

<template>
  <span class="risk-badge" :class="[`risk-${level.toLowerCase()}`, { compact }]" :aria-label="score === null ? label : `${label}，风险分数${score}`">
    <el-icon class="risk-icon" aria-hidden="true"><component :is="icon" /></el-icon>
    <span v-if="score !== null" class="risk-score">{{ score }}</span>
    <span class="risk-tag-label">{{ label }}</span>
    <span class="sr-only">{{ compact ? level : '' }} {{ level === 'YELLOW' ? '建议关注' : '' }} {{ level === 'UNKNOWN' ? '不可判定 人工复核' : '' }}</span>
  </span>
</template>
