import { createHash } from 'node:crypto'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const files = [
  'fall-risk-replay.mp4',
  'activity-route-replay-browser.mp4',
  'daily-baseline-replay-browser.mp4',
]
const failures = []
for (const name of files) {
  const publicPath = resolve(root, 'public/media', name)
  if (!existsSync(publicPath) || statSync(publicPath).size === 0) {
    failures.push(`${name}: public 文件不存在或为空`)
    continue
  }
  const bytes = readFileSync(publicPath)
  const signature = bytes.toString('ascii')
  if (!signature.includes('avc1') || signature.includes('hvc1')) failures.push(`${name}: 不是纯 H.264 avc1 文件`)
  const distPath = resolve(root, 'dist/media', name)
  if (existsSync(distPath)) {
    const publicHash = createHash('sha256').update(bytes).digest('hex')
    const distHash = createHash('sha256').update(readFileSync(distPath)).digest('hex')
    if (publicHash !== distHash) failures.push(`${name}: public 与 dist SHA-256 不一致`)
  }
}
if (failures.length) {
  console.error(failures.join('\n'))
  process.exit(1)
}
console.log(`浏览器媒体校验通过：${files.length} 个 H.264 文件`)
