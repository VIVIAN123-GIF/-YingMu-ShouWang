import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { routes } from '../router'

describe('统一家属端信息架构', () => {
  it('提供九个冻结一级导航入口', () => {
    expect(routes.filter((route) => route.meta?.nav)).toHaveLength(9)
  })

  it('核心页面不包含禁止使用的武断文案', () => {
    const files = ['HomeView.vue', 'EventDetailView.vue', 'WeeklyView.vue']
    const forbidden = ['你要跌倒了', '你被骗了', '你得了抑郁症']
    const contents = files.map((file) => readFileSync(resolve(process.cwd(), 'src', 'views', file), 'utf8')).join('\n')
    forbidden.forEach((phrase) => expect(contents).not.toContain(phrase))
  })
})
