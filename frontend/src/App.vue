<script setup>
import AppShell from './components/layout/AppShell.vue'
import DemoLogin from './components/auth/DemoLogin.vue'
import { demoAuthState, demoLoginConfig } from './services/demoAuth'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
</script>

<template>
  <el-config-provider :locale="zhCn">
    <DemoLogin
      v-if="demoLoginConfig.enabled && !demoAuthState.authenticated"
      @authenticated="demoAuthState.authenticated = true"
    />
    <AppShell v-else @logout="demoAuthState.authenticated = false" />
  </el-config-provider>
</template>
