import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient, exportAuditLog, getEventExplanation, setDataMode } from '../services/repository'
import { validateAgentExplanationJob } from '../domain/validation'

const successResponse = {
  event_id: 'event-agent-1', status: 'SUCCESS', request_id: 'agent-event-agent-1',
  event_version_hash: 'version-1', generated_by: 'qwen3.6-flash', fallback_used: false,
  attempt_count: 1, error_code: null, created_at: null, completed_at: null,
  explanation: {
    schema_version: 'agent-explanation/1.0', request_id: 'agent-event-agent-1', event_id: 'event-agent-1',
    summary: 'Structured explanation', reasoning_points: ['Evidence reason'],
    recommended_action_text: 'Sit safely', capability_notice: 'Structured event only',
    generated_by: 'qwen3.6-flash', fallback_used: false,
  },
}

const safeSuccessResponse = {
  event_id: 'event-agent-1', status: 'SUCCESS', attempt_count: 1,
  created_at: null, completed_at: null,
  explanation: {
    summary: 'Structured explanation', reasoning_points: ['Evidence reason'],
    recommended_action_text: 'Sit safely', capability_notice: 'Structured event only',
    generated_by: 'qwen3.6-flash', fallback_used: false,
  },
}

describe('event explanation repository', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    setDataMode('auto')
  })

  it('requests only the encoded GET endpoint and returns the safe response projection', async () => {
    setDataMode('api')
    const encodedResponse = structuredClone(successResponse)
    encodedResponse.event_id = 'event agent/1'
    encodedResponse.explanation.event_id = 'event agent/1'
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: encodedResponse })
    const post = vi.spyOn(apiClient, 'post')

    await expect(getEventExplanation('event agent/1')).resolves.toEqual({
      ...safeSuccessResponse,
      event_id: 'event agent/1',
    })
    expect(get).toHaveBeenCalledWith('/events/event%20agent%2F1/explanation')
    expect(get.mock.calls[0]).toHaveLength(1)
    expect(JSON.stringify(get.mock.calls[0])).not.toContain('X-Control-Token')
    expect(post).not.toHaveBeenCalled()
  })

  it.each(['api', 'auto', 'mock'])('uses the backend GET without frontend fallback in %s mode', async (mode) => {
    setDataMode(mode)
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: successResponse })

    const result = await getEventExplanation('event-agent-1')

    expect(result.status).toBe('SUCCESS')
    expect(get).toHaveBeenCalledOnce()
  })

  it('reads indexed replay explanations locally in auto mode without a failing API request', async () => {
    setDataMode('auto')
    const get = vi.spyOn(apiClient, 'get')

    const result = await getEventExplanation('event-fall-100')

    expect(result.event_id).toBe('event-fall-100')
    expect(result.status).toBe('FALLBACK')
    expect(result.explanation.capability_notice).toBe('授权回放')
    expect(get).not.toHaveBeenCalled()
  })

  it('drops sensitive extension fields before returning or recording the result', async () => {
    setDataMode('api')
    const response = structuredClone(successResponse)
    Object.assign(response, {
      token: 'secret-token-value',
      device_serial: 'DEVICE-SERIAL-001',
      file_path: 'C:\\private\\resident\\recording.wav',
      temporary_url: 'https://temporary.example.test/private-stream',
      raw_transcript: 'raw-private-transcript',
    })
    Object.assign(response.explanation, {
      api_key: 'secret-api-key',
      raw_transcript: 'nested-private-transcript',
    })
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: response })

    const result = await getEventExplanation('event-agent-1')
    const serialized = JSON.stringify(result)
    const audit = JSON.stringify(exportAuditLog().slice(-1))

    ;['secret-token-value', 'DEVICE-SERIAL-001', 'recording.wav', 'temporary.example.test',
      'raw-private-transcript', 'secret-api-key', 'nested-private-transcript']
      .forEach((secret) => {
        expect(serialized).not.toContain(secret)
        expect(audit).not.toContain(secret)
      })
  })

  it.each(['auto', 'mock'])('rejects backend failures without mock fallback in %s mode and records no raw error', async (mode) => {
    setDataMode(mode)
    const secretError = new Error('token=secret-error-token https://temporary.example.test/media')
    vi.spyOn(apiClient, 'get').mockRejectedValue(secretError)

    await expect(getEventExplanation('event-agent-1')).rejects.toBe(secretError)
    const audit = JSON.stringify(exportAuditLog().slice(-1))
    expect(audit).not.toContain('secret-error-token')
    expect(audit).not.toContain('temporary.example.test')
  })

  it('accepts NOT_REQUESTED as a non-terminal empty explanation state', () => {
    expect(validateAgentExplanationJob({
      event_id: 'event-agent-1', status: 'NOT_REQUESTED', request_id: null,
      event_version_hash: null, explanation: null, generated_by: null, fallback_used: null,
      attempt_count: 0, error_code: null, created_at: null, completed_at: null,
    })).toEqual({
      event_id: 'event-agent-1', status: 'NOT_REQUESTED', explanation: null,
      attempt_count: 0, created_at: null, completed_at: null,
    })
  })
})
