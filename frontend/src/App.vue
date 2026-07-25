<script setup>
import AppShell from './components/layout/AppShell.vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
</script>

<template>
  <el-config-provider :locale="zhCn">
    <AppShell />
  </el-config-provider>
</template>
