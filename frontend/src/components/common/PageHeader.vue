<script setup>
defineProps({
  eyebrow: { type: String, default: '萤目守望 · 统一家属端' },
  title: { type: String, required: true },
  description: { type: String, default: '' },
})
</script>

<template>
  <header class="page-header">
    <div>
      <span class="eyebrow">{{ eyebrow }}</span>
      <h1>{{ title }}</h1>
      <p v-if="description">{{ description }}</p>
    </div>
    <div class="page-header-actions"><slot /></div>
  </header>
</template>
