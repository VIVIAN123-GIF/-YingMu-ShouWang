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
    <section class="demo-login-shell" aria-labelledby="demo-login-title">
      <div class="demo-login-aside">
        <div class="demo-login-brand" aria-hidden="true">萤</div>
        <span class="demo-login-kicker">家庭安全控制台</span>
        <h1 id="demo-login-title">萤目守望</h1>
        <p>受控访问设备状态、风险事件和授权媒体。</p>
        <div class="demo-login-status"><span class="demo-login-status-dot" aria-hidden="true"></span><span>媒体会话服务就绪</span></div>
      </div>

      <div class="demo-login-panel">
        <div class="demo-login-heading"><span>受权入口</span><strong>登录控制台</strong></div>

        <form class="demo-login-form" @submit.prevent="submit">
          <label>
            <span>用户名</span>
            <el-input v-model="form.username" autocomplete="username" size="large" aria-label="用户名" placeholder="输入受权用户名">
              <template #prefix><el-icon><User /></el-icon></template>
            </el-input>
          </label>
          <label>
            <span>密码</span>
            <el-input v-model="form.password" type="password" show-password autocomplete="current-password" size="large" aria-label="密码" placeholder="输入访问密码">
              <template #prefix><el-icon><Lock /></el-icon></template>
            </el-input>
          </label>
          <p v-if="errorMessage" class="demo-login-error" role="alert">{{ errorMessage }}</p>
          <el-button native-type="submit" type="primary" size="large" :loading="submitting">进入控制台</el-button>
        </form>

        <small>登录仅用于当前控制台会话，站点不保存密码或媒体令牌。</small>
      </div>
    </section>
  </main>
</template>
