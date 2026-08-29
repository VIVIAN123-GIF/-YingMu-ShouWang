<script setup>
defineProps({
  title: { type: String, required: true },
  type: { type: String, default: 'info' },
  description: { type: String, default: '' },
})
</script>

<template>
  <el-alert class="standard-notice" :title="title" :description="description" :type="type" show-icon :closable="false" />
</template>
