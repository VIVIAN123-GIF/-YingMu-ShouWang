import { afterEach, describe, expect, it, vi } from 'vitest'
import events from '../mocks/events.json'
import {
  API_BASE_URL, apiClient, normalizeApiError, runtime, setDataMode, submitFamilyFeedback, submitInterventionResult,
} from '../services/repository'

describe('前端对接文档请求契约', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    setDataMode('auto')
  })

  it('默认使用 /api/v1，且请求路径不重复拼接前缀', () => {
    expect(API_BASE_URL).toBe('/api/v1')
    expect(apiClient.defaults.baseURL).toBe('/api/v1')
  })

  it('解析标准错误响应并保留 request_id', () => {
    const error = { message: 'Request failed', response: { data: {
      error: { code: 'EVENT_NOT_FOUND', message: '事件不存在', request_id: 'req-001' },
    } } }
    const normalized = normalizeApiError(error)
    expect(normalized.api).toEqual({ code: 'EVENT_NOT_FOUND', message: '事件不存在', request_id: 'req-001' })
    expect(normalized.message).toContain('request_id: req-001')
  })

  it('干预调用文档指定的 /events/{id}/intervene', async () => {
    setDataMode('api')
    const response = { schema_version: '1.0', result_id: 'result-1', event_id: 'event-fall-intervening',
      started_at: '2026-08-11T15:00:00+08:00', completed_at: null, action_type: 'voice', tool_name: 'mock_voice',
      delivery_status: 'SUCCESS', resident_response: null, family_feedback: null, risk_after: null,
      resolved: false, resolution_reason: null, operator: 'system', source_mode: 'MOCK', simulated: true }
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: response })
    await submitInterventionResult(structuredClone(events.find((event) => event.event_id === 'event-fall-intervening')))
    expect(post).toHaveBeenCalledWith('/events/event-fall-intervening/intervene', null, expect.any(Object))
    expect(post.mock.calls[0][2].headers['Content-Type']).toBe('application/json; charset=utf-8')
  })

  it('家属反馈固定提交 confirm 与 JSON 内容类型', async () => {
    setDataMode('api')
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { result_id: 'feedback-1' } })
    await submitFamilyFeedback('event-mental-week', { feedback_type: 'care', value: '已联系家属', operator: 'family' })
    expect(post).toHaveBeenCalledWith('/events/event-mental-week/feedback', expect.objectContaining({
      feedback_type: 'confirm', value: '已联系家属', operator: 'family',
    }), expect.any(Object))
    expect(post.mock.calls[0][2].headers['Content-Type']).toBe('application/json; charset=utf-8')
  })
})
