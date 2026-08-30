<script setup>
defineProps({
  title: { type: String, default: '工程与评审详情' },
  summary: { type: String, default: '规则、版本、质量和审计信息' },
})
</script>

<template>
  <section class="technical-disclosure open" :aria-label="title" :data-summary="summary">
    <div class="technical-disclosure-content"><slot /></div>
  </section>
</template>
