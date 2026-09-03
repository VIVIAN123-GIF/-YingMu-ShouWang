import { reactive } from 'vue'
import { sha256 } from 'js-sha256'

const SESSION_KEY = 'yingmu-demo-authenticated'
const MEDIA_BFF_ENABLED = import.meta.env.VITE_MEDIA_BFF_ENABLED !== 'false'

export const demoLoginConfig = Object.freeze({
  enabled: import.meta.env.VITE_DEMO_LOGIN_ENABLED === 'true',
  username: import.meta.env.VITE_DEMO_USER || '',
  passwordSha256: (import.meta.env.VITE_DEMO_PASSWORD_SHA256 || '').toLowerCase(),
})

function sessionIsAuthenticated() {
  return !demoLoginConfig.enabled || sessionStorage.getItem(SESSION_KEY) === 'true'
}

export const demoAuthState = reactive({
  authenticated: sessionIsAuthenticated(),
})

export async function sha256Hex(value) {
  // 使用纯 JS 实现的 js-sha256，兼容 HTTP（非安全上下文）环境。
  // 浏览器原生 crypto.subtle 仅在 HTTPS / localhost 下可用，公网 HTTP IP 下为 null 会抛异常。
  return sha256(value)
}

export async function verifyDemoCredentials(username, password, config = demoLoginConfig) {
  if (!config.username || !config.passwordSha256) return false
  const digest = await sha256Hex(password)
  return username === config.username && digest === config.passwordSha256.toLowerCase()
}

export async function loginToDemo(username, password) {
  if (!demoLoginConfig.enabled) {
    demoAuthState.authenticated = true
    return true
  }
  const accepted = await verifyDemoCredentials(username, password)
  if (accepted && MEDIA_BFF_ENABLED) {
    const response = await fetch('/api/v1/media/session', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!response.ok) return false
  }
  if (accepted) {
    sessionStorage.setItem(SESSION_KEY, 'true')
    demoAuthState.authenticated = true
  }
  return accepted
}

export function logoutOfDemo() {
  sessionStorage.removeItem(SESSION_KEY)
  demoAuthState.authenticated = !demoLoginConfig.enabled
  if (MEDIA_BFF_ENABLED) {
    void fetch('/api/v1/media/session', { method: 'DELETE', credentials: 'include' }).catch(() => {})
  }
}
