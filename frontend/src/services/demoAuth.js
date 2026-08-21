import { reactive } from 'vue'

const SESSION_KEY = 'yingmu-demo-authenticated'

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
  const bytes = new TextEncoder().encode(value)
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')
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
  if (accepted) {
    sessionStorage.setItem(SESSION_KEY, 'true')
    demoAuthState.authenticated = true
  }
  return accepted
}

export function logoutOfDemo() {
  sessionStorage.removeItem(SESSION_KEY)
  demoAuthState.authenticated = !demoLoginConfig.enabled
}
