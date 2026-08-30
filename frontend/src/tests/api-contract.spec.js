import { afterEach, describe, expect, it, vi } from 'vitest'
import events from '../replay-data/events.json'
import {
  API_BASE_URL, apiClient, getAsset, getBaseline, getEvent, getWeeklyReport, interveneEvent, normalizeApiError, runtime, setDataMode, submitFamilyFeedback, submitInterventionResult,
} from '../services/repository'

describe('前端对接文档请求契约', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    setDataMode('auto')
  })

  it('使用当前 API 基址，且请求路径不重复拼接前缀', () => {
    expect(API_BASE_URL).toMatch(/\/api\/v1\/?$/)
    expect(apiClient.defaults.baseURL).toBe(API_BASE_URL)
  })

  it('周报和个人基线使用后端 API，并保留查询居民标识', async () => {
    setDataMode('api')
    const get = vi.spyOn(apiClient, 'get')
      .mockResolvedValueOnce({ data: { resident_id: 'resident-api', trend: [], evidence: [], recommendations: [], care: {} } })
      .mockResolvedValueOnce({ data: { resident_id: 'resident api/1', baselines: {} } })

    await getWeeklyReport('resident-api')
    await getBaseline('resident api/1')

    expect(get).toHaveBeenNthCalledWith(1, '/reports/weekly', { params: { resident_id: 'resident-api' } })
    expect(get).toHaveBeenNthCalledWith(2, '/residents/resident%20api%2F1/baseline')
  })

  it('素材读取使用编码后的 /assets/{id}，不重复拼接 API 前缀', async () => {
    setDataMode('api')
    const asset = {
      asset_id: 'asset api/1', title: '授权素材', source_mode: 'RECORDED_REPLAY', simulated: true,
      stream_url: null, fallback_url: null, fallback_kind: 'unavailable', available: false,
      verification_status: 'PENDING', captured_at: '2026-08-11T15:00:00+08:00', notice: '暂无文件',
    }
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: asset })

    await expect(getAsset('asset api/1')).resolves.toEqual(asset)
    expect(get).toHaveBeenCalledWith('/assets/asset%20api%2F1')
  })

  it('同一缺失素材的并发和后续读取复用一次 404 结果', async () => {
    setDataMode('api')
    const error = Object.assign(new Error('authorized asset does not exist'), {
      response: { status: 404 }, api: { code: 'ASSET_NOT_FOUND' },
    })
    const get = vi.spyOn(apiClient, 'get').mockRejectedValue(error)

    const firstPair = await Promise.allSettled([getAsset('asset-missing-1'), getAsset('asset-missing-1')])
    await expect(getAsset('asset-missing-1')).rejects.toBe(error)

    expect(firstPair.map((result) => result.status)).toEqual(['rejected', 'rejected'])
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('解析标准错误响应并保留 request_id', () => {
    const error = { message: 'Request failed', response: { data: {
      error: { code: 'EVENT_NOT_FOUND', message: '事件不存在', request_id: 'req-001' },
    } } }
    const normalized = normalizeApiError(error)
    expect(normalized.api).toEqual({ code: 'EVENT_NOT_FOUND', message: '事件不存在', request_id: 'req-001' })
    expect(normalized.message).toContain('request_id: req-001')
  })

  it('事件详情读取对路径中的特殊字符进行编码', async () => {
    setDataMode('api')
    const eventId = 'event detail/一'
    const event = structuredClone(events[0])
    event.event_id = eventId
    event.interventions = []
    const get = vi.spyOn(apiClient, 'get')
      .mockResolvedValueOnce({ data: event })
      .mockResolvedValueOnce({ data: [] })

    await getEvent(eventId)

    expect(get).toHaveBeenNthCalledWith(1, '/events/event%20detail%2F%E4%B8%80')
    expect(get).toHaveBeenNthCalledWith(2, '/events/event%20detail%2F%E4%B8%80/forewarning')
  })

  it('将网络错误转换为用户可理解的中文', () => {
    expect(normalizeApiError({ message: 'Network Error' }).message).toBe('网络连接失败')
    expect(normalizeApiError({ message: 'timeout', code: 'ECONNABORTED' }).message).toBe('请求超时')
  })

  it('干预调用文档指定的 /events/{id}/intervene', async () => {
    setDataMode('api')
    const response = { schema_version: '1.0', result_id: 'result-1', event_id: 'event-fall-intervening',
      started_at: '2026-08-11T15:00:00+08:00', completed_at: null, action_type: 'voice', tool_name: 'mock_voice',
      delivery_status: 'SUCCESS', resident_response: null, family_feedback: null, risk_after: null,
      resolved: false, resolution_reason: null, operator: 'system', source_mode: 'RECORDED_REPLAY', simulated: true }
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: response })
    await interveneEvent('event-fall-intervening')
    expect(post).toHaveBeenCalledWith('/events/event-fall-intervening/intervene', null, expect.any(Object))
    expect(post.mock.calls[0][2].headers['Content-Type']).toBe('application/json; charset=utf-8')
  })

  it('坐稳确认向 /events/{id}/results 提交完整 InterventionResult', async () => {
    setDataMode('api')
    const current = structuredClone(events.find((event) => event.event_id === 'event-fall-intervening'))
    const response = {
      schema_version: '1.0', result_id: 'result-stable', event_id: current.event_id,
      started_at: '2026-08-11T15:00:00+08:00', completed_at: '2026-08-11T15:00:00+08:00',
      action_type: 'resident_response', tool_name: 'family_console', delivery_status: 'SUCCESS',
      resident_response: 'stable', family_feedback: null, risk_after: null, resolved: false,
      resolution_reason: null, operator: 'family', source_mode: 'RECORDED_REPLAY', simulated: true,
    }
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: response })

    await submitInterventionResult(current, 'stable')

    expect(post).toHaveBeenCalledWith(
      '/events/event-fall-intervening/results',
      expect.objectContaining({
        schema_version: '1.0', event_id: current.event_id, action_type: 'resident_response',
        resident_response: 'stable', resolved: false,
      }),
      expect.any(Object),
    )
    expect(post.mock.calls[0][2].headers['Content-Type']).toBe('application/json; charset=utf-8')
  })

  it('家属反馈固定提交 confirm 与 JSON 内容类型', async () => {
    setDataMode('api')
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { result_id: 'feedback-1' } })
    await submitFamilyFeedback('event mental/一', { feedback_type: 'care', value: '已联系家属', operator: 'family' })
    expect(post).toHaveBeenCalledWith('/events/event%20mental%2F%E4%B8%80/feedback', expect.objectContaining({
      feedback_type: 'confirm', value: '已联系家属', operator: 'family',
    }), expect.any(Object))
    expect(post.mock.calls[0][2].headers['Content-Type']).toBe('application/json; charset=utf-8')
  })
})
