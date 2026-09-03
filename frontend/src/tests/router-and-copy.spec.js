import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { routes } from '../router'

describe('统一家属端信息架构', () => {
  it('提供八个去重后的一级导航入口，详情页只从事件列表进入', () => {
    expect(routes.filter((route) => route.meta?.nav)).toHaveLength(8)
    expect(routes.find((route) => route.name === 'event-detail')).toMatchObject({
      path: '/events/:eventId', meta: { nav: false },
    })
    expect(routes.find((route) => route.name === 'scene-calibration')).toMatchObject({
      path: '/system/calibration/:sceneConfigId', meta: { nav: false },
    })
    expect(routes.find((route) => route.name === 'events')?.meta.title).toBe('风险事件与处置')
    expect(routes.find((route) => route.name === 'replay')?.meta.title).toBe('风险验证与回放')
  })

  it('核心页面不包含禁止使用的武断文案', () => {
    const files = ['HomeView.vue', 'EventDetailView.vue', 'WeeklyView.vue']
    const forbidden = ['你要跌倒了', '你被骗了', '你得了抑郁症']
    const contents = files.map((file) => readFileSync(resolve(process.cwd(), 'src', 'views', file), 'utf8')).join('\n')
    forbidden.forEach((phrase) => expect(contents).not.toContain(phrase))
  })
})
