import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('关怀与身份核验反馈记录', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
    sessionStorage.clear()
  })

  it('回放模式分别持久化 CARE 和 IDENTITY_VERIFICATION，并可读取', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'replay')
    const { getAllRecordedFeedback, getRecordedFeedback, submitFamilyFeedback } = await import('../services/repository')
    const care = await submitFamilyFeedback('event-mental-week', { feedback_kind: 'CARE', value: '已联系，希望继续关注', operator: 'family' })
    const identity = await submitFamilyFeedback('event-fraud-visitor', { feedback_kind: 'IDENTITY_VERIFICATION', value: '存在财产风险，转人工处理', operator: 'family' })
    expect(care).toMatchObject({ event_id: 'event-mental-week', feedback_kind: 'CARE', source_mode: 'RECORDED_REPLAY', simulated: true, saved_in_demo: true })
    expect(identity).toMatchObject({ event_id: 'event-fraud-visitor', feedback_kind: 'IDENTITY_VERIFICATION' })
    expect(getRecordedFeedback('event-mental-week')).toHaveLength(1)
    expect(getAllRecordedFeedback()).toHaveLength(2)
  })

  it('相同事件、类型和选项保持幂等，清除后记录消失', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'replay')
    const { clearRecordedFeedback, getAllRecordedFeedback, submitFamilyFeedback } = await import('../services/repository')
    const input = { feedback_kind: 'CARE', value: '已联系，近期一切正常', operator: 'family' }
    const first = await submitFamilyFeedback('event-mental-week', input)
    const second = await submitFamilyFeedback('event-mental-week', input)
    expect(second.feedback_id).toBe(first.feedback_id)
    expect(getAllRecordedFeedback()).toHaveLength(1)
    clearRecordedFeedback()
    expect(getAllRecordedFeedback()).toEqual([])
  })

  it('API 模式读取不到离线回放记录', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'api')
    localStorage.setItem('yingmu-feedback-records-v1', JSON.stringify([{ event_id: 'event-1', feedback_kind: 'CARE' }]))
    const { getAllRecordedFeedback } = await import('../services/repository')
    expect(getAllRecordedFeedback()).toEqual([])
  })
})
