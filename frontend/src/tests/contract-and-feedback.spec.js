import { describe, expect, it } from 'vitest'
import events from '../mocks/events.json'
import dashboard from '../mocks/dashboard.json'
import { DataContractError, validateDashboard, validateRiskEvent } from '../domain/validation'
import { setDataMode, stableFeedbackId, submitFamilyFeedback } from '../services/repository'

describe('0—1 风险分契约', () => {
  it('所有 Mock 风险分和风险历史均位于0—1', () => {
    events.forEach((event) => {
      expect(event.risk_score).toBeGreaterThanOrEqual(0)
      expect(event.risk_score).toBeLessThanOrEqual(1)
      event.risk_history.forEach((point) => expect(point.score).toBeLessThanOrEqual(1))
      event.interventions.forEach((result) => {
        if (result.risk_after !== null) expect(result.risk_after).toBeLessThanOrEqual(1)
      })
      expect(() => validateRiskEvent(event)).not.toThrow()
    })
    expect(() => validateDashboard(dashboard)).not.toThrow()
  })

  it('拒绝旧的0—100风险分，不由前端猜测换算', () => {
    const invalid = structuredClone(events[0])
    invalid.risk_score = 84
    expect(() => validateRiskEvent(invalid)).toThrow(DataContractError)
  })
})

describe('家属反馈幂等', () => {
  it('相同事件和反馈生成稳定ID并复用第一次结果', async () => {
    setDataMode('mock')
    const feedback = { feedback_type: 'care', value: '已联系，希望继续关注', operator: 'family' }
    const id = stableFeedbackId('event-mental-week', feedback)
    expect(id).toBe(stableFeedbackId('event-mental-week', feedback))
    const first = await submitFamilyFeedback('event-mental-week', feedback)
    const second = await submitFamilyFeedback('event-mental-week', feedback)
    expect(first.feedback_id).toBe(id)
    expect(second).toEqual(first)
  })
})
