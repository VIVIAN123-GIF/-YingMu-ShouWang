<script setup>
import { computed } from 'vue'
import { StarFilled } from '@element-plus/icons-vue'
import { RISK_LEVELS } from '../../domain/constants'

const props = defineProps({
  level: { type: String, default: 'GREEN' },
  compact: Boolean,
  score: { type: [Number, String], default: null },
})

const unknownConfig = Object.freeze({ label: '需人工复核', color: '#6B7280' })
const config = computed(() => RISK_LEVELS[props.level] || unknownConfig)
const label = computed(() => config.value.label || '需人工复核')
const starCount = computed(() => ({ GREEN: 1, YELLOW: 2, ORANGE: 3, RED: 3 }[props.level] || 0))
</script>

<template>
  <span class="risk-badge" :class="[`risk-${level.toLowerCase()}`, { compact }]" :aria-label="score === null ? `${label}，${starCount}星` : `${label}，风险分数${score}，${starCount}星`">
    <span v-if="score !== null" class="risk-score">{{ score }}</span>
    <span v-if="starCount" class="risk-stars" aria-hidden="true">
      <el-icon v-for="index in starCount" :key="index"><StarFilled /></el-icon>
    </span>
    <span v-else class="risk-unknown-mark" aria-hidden="true">?</span>
    <span class="risk-level-label">{{ label }}</span>
    <span class="sr-only">{{ compact ? level : '' }} {{ level === 'YELLOW' ? '建议关注' : '' }} {{ level === 'UNKNOWN' ? '不可判定 人工复核' : '' }}</span>
  </span>
</template>
