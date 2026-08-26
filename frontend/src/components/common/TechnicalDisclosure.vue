<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { useViewMode } from '../../services/viewMode'

defineProps({
  title: { type: String, default: '工程与评审详情' },
  summary: { type: String, default: '规则、版本、质量和审计信息' },
})
const { isReview } = useViewMode()
const familyOpen = ref(false)
const open = computed(() => isReview.value || familyOpen.value)
watch(isReview, (review) => { if (review) familyOpen.value = false })
</script>

<template>
  <section class="technical-disclosure" :class="{ open }">
    <button v-if="!isReview" type="button" class="technical-disclosure-trigger" :aria-expanded="open" @click="familyOpen = !familyOpen">
      <span><strong>{{ title }}</strong><small>{{ summary }}</small></span>
      <el-icon><component :is="open ? ArrowUp : ArrowDown" /></el-icon>
    </button>
    <div v-if="open" class="technical-disclosure-content"><slot /></div>
  </section>
</template>
