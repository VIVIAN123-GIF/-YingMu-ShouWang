import { describe, expect, it } from 'vitest'
import { sha256Hex, verifyDemoCredentials } from '../services/demoAuth'

const config = {
  username: 'judge',
  passwordSha256: '5b3ae551dac553f2974efbc195e6974edd42410447ddb53cf41aa7c02fd4f19d',
}

describe('Pages评审访问门禁', () => {
  it('使用固定SHA-256摘要校验正确账号', async () => {
    expect(await sha256Hex('YingMu2026Review!')).toBe(config.passwordSha256)
    await expect(verifyDemoCredentials('judge', 'YingMu2026Review!', config)).resolves.toBe(true)
  })

  it('拒绝错误用户名和错误密码', async () => {
    await expect(verifyDemoCredentials('other', 'YingMu2026Review!', config)).resolves.toBe(false)
    await expect(verifyDemoCredentials('judge', 'wrong-password', config)).resolves.toBe(false)
  })
})
