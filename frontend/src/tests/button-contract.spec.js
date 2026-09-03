import { readFileSync, readdirSync } from 'node:fs'
import { extname, join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

function vueFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return vueFiles(path)
    return extname(entry.name) === '.vue' ? [path] : []
  })
}

describe('前端按钮交互契约', () => {
  it('每个真实按钮都有点击处理或表单提交行为', () => {
    const sourceRoot = join(process.cwd(), 'src')
    const failures = vueFiles(sourceRoot).flatMap((file) => {
      const source = readFileSync(file, 'utf8')
      const openingTags = source.match(/<(?:el-button|button)\b[^>]*>/g) || []
      return openingTags
        .filter((tag) => !/@click(?:\.|=)/.test(tag) && !/(?:native-)?type=["']submit["']/.test(tag))
        .map((tag) => `${relative(sourceRoot, file)}: ${tag.replace(/\s+/g, ' ')}`)
    })

    expect(failures).toEqual([])
  })
})
