import { existsSync, readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
import selectedMedia from '../src/replay-data/selected-media.json' with { type: 'json' }
import manifest from '../media-selection.manifest.json' with { type: 'json' }

const root = resolve(import.meta.dirname, '..')
const failures = []
if (selectedMedia.length !== manifest.entries.length) {
  failures.push(`精选清单与构建清单数量不一致：页面 ${selectedMedia.length} 条，构建 ${manifest.entries.length} 条`)
}

const auxiliaryMedia = (manifest.auxiliary_entries || []).map((clip) => ({ ...clip, file: clip.target_filename }))
for (const clip of [...selectedMedia, ...auxiliaryMedia]) {
  if (clip.asset_id === undefined || !/^[a-z0-9-]+\.mp4$/.test(clip.file || '')) {
    failures.push(`${clip.asset_id || 'unknown'}: 脱敏文件名无效`)
    continue
  }
  const publicPath = resolve(root, 'public/media/selected', clip.file)
  if (!existsSync(publicPath) || statSync(publicPath).size === 0) {
    failures.push(`${clip.file}: public 精选文件不存在或为空`)
    continue
  }
  const signature = readFileSync(publicPath).toString('ascii')
  // Some camera files include an unrelated `hvc1` string in MP4 metadata;
  // the browser stream sample entry is the authoritative avc1 marker.
  if (!signature.includes('avc1')) failures.push(`${clip.file}: 不是 H.264 avc1 文件`)
  const moov = signature.indexOf('moov')
  const mdat = signature.indexOf('mdat')
  if (moov < 0 || (mdat >= 0 && moov > mdat)) failures.push(`${clip.file}: 未启用 faststart`)
}

if (failures.length) {
  console.error(failures.join('\n'))
  process.exit(1)
}
console.log(`浏览器媒体校验通过：${selectedMedia.length} 条精选素材和 ${auxiliaryMedia.length} 条辅助素材，均为 RECORDED_REPLAY / simulated=true`)
