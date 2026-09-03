<script setup>
import { ref } from 'vue'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'

const props = defineProps({
  title: { type: String, default: '工程与评审详情' },
  summary: { type: String, default: '规则、版本、质量和审计信息' },
  defaultOpen: { type: Boolean, default: false },
})

const open = ref(props.defaultOpen)

function toggle() {
  open.value = !open.value
}
</script>

<template>
  <section class="technical-disclosure" :class="{ open }" :aria-label="title" :data-summary="summary">
    <button
      type="button"
      class="technical-disclosure-trigger"
      :aria-expanded="open"
      @click="toggle"
    >
      <span><strong>{{ title }}</strong><small>{{ summary }}</small></span>
      <span class="technical-disclosure-action">
        {{ open ? '收起' : '展开' }}
        <el-icon><ArrowUp v-if="open" /><ArrowDown v-else /></el-icon>
      </span>
    </button>
    <div v-if="open" class="technical-disclosure-content"><slot /></div>
  </section>
</template>
