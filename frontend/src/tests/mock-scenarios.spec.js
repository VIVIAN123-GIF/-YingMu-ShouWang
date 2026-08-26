import { describe, expect, it } from 'vitest'
import events from '../mocks/events.json'
import forewarning from '../mocks/forewarning.json'
import weekly from '../mocks/weekly.json'

describe('固定 JSON 演示闭环', () => {
  it('跌倒场景完整经过干预、观察和回落', () => {
    const event = events.find((item) => item.event_id === 'event-fall-100')
    expect(event.timeline.map((item) => item.status)).toEqual([
      'ORANGE', 'INTERVENING', 'SUCCESS', 'OBSERVING', 'RESOLVED',
    ])
    expect(event.evidence_summary.some((item) => item.evidence_type === 'posture_recovered')).toBe(true)
    expect(event.interventions[0].resolved).toBe(true)
  })

  it('事件详情保留模拟来源和干预前后工程指数', () => {
    const snapshots = forewarning.filter((item) => item.event_id === 'event-fall-100')
    expect(snapshots.map((item) => item.phase)).toEqual(['PRE_INTERVENTION', 'POST_INTERVENTION'])
    expect(snapshots[1].instant.engineering_index).toBeLessThan(snapshots[0].instant.engineering_index)
    expect(snapshots.every((item) => item.source_mode === 'MOCK' && item.simulated)).toBe(true)
  })

  it('诈骗核验包含访客、停留和关键词三类证据', () => {
    expect(weekly.visitor_case.evidence.map((item) => item.type)).toEqual([
      'unauthorized_visitor', 'unusual_dwell_time', 'fraud_keyword',
    ])
  })

  it('工具失败场景保留 FAILED 且未标记回落', () => {
    const event = events.find((item) => item.event_id === 'event-tool-failed')
    expect(event.interventions[0].delivery_status).toBe('FAILED')
    expect(event.interventions[0].resolved).toBe(false)
  })

  it('黄色周报只表达趋势与关怀建议', () => {
    expect(weekly.risk_level).toBe('YELLOW')
    expect(weekly.summary).toContain('建议家属')
    expect(weekly.summary).not.toMatch(/抑郁症|认知症|医学诊断/)
  })
})
