<script setup>
import { reactive, ref } from 'vue'
import { Lock, User } from '@element-plus/icons-vue'
import { loginToDemo } from '../../services/demoAuth'

const emit = defineEmits(['authenticated'])
const form = reactive({ username: '', password: '' })
const submitting = ref(false)
const errorMessage = ref('')

async function submit() {
  if (submitting.value) return
  submitting.value = true
  errorMessage.value = ''
  try {
    if (await loginToDemo(form.username, form.password)) {
      emit('authenticated')
      return
    }
    errorMessage.value = '账号或密码不正确'
  } catch {
    errorMessage.value = '无法完成登录校验，请刷新后重试'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="demo-login-page">
    <section class="demo-login-panel" aria-labelledby="demo-login-title">
      <div class="demo-login-brand" aria-hidden="true">萤</div>
      <div>
        <span class="demo-login-kicker">赛事评审入口</span>
        <h1 id="demo-login-title">萤目守望</h1>
        <p>请输入评审账号进入脱敏演示。</p>
      </div>

      <form class="demo-login-form" @submit.prevent="submit">
        <label>
          <span>用户名</span>
          <el-input v-model="form.username" autocomplete="username" size="large" aria-label="用户名">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </label>
        <label>
          <span>密码</span>
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" size="large" aria-label="密码">
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </label>
        <p v-if="errorMessage" class="demo-login-error" role="alert">{{ errorMessage }}</p>
        <el-button native-type="submit" type="primary" size="large" :loading="submitting">进入演示</el-button>
      </form>

      <div class="demo-login-boundaries" aria-label="演示数据边界">
        <span>脱敏演示数据</span>
        <span>RECORDED_REPLAY / 授权回放</span>
        <span>非实时设备</span>
        <span>非老年人实测</span>
      </div>
      <small>静态访问门禁，不是生产级身份认证。站点不托管敏感数据。</small>
    </section>
  </main>
</template>
