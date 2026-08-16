import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient, getEventExplanation, runtime, setDataMode } from '../services/repository'
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

describe('event explanation repository', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    setDataMode('auto')
  })

  it('requests the event explanation endpoint and validates the response', async () => {
    setDataMode('api')
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: successResponse })

    await expect(getEventExplanation('event-agent-1')).resolves.toEqual(successResponse)
    expect(get).toHaveBeenCalledWith('/events/event-agent-1/explanation')
    expect(runtime.activeSource).toBe('api')
  })

  it('returns a fixed explanation in mock mode without an API request', async () => {
    setDataMode('mock')
    const get = vi.spyOn(apiClient, 'get')

    const result = await getEventExplanation('event-agent-1')

    expect(result.status).toBe('SUCCESS')
    expect(result.event_id).toBe('event-agent-1')
    expect(get).not.toHaveBeenCalled()
  })

  it('accepts NOT_REQUESTED as a terminal empty explanation state', () => {
    expect(validateAgentExplanationJob({
      event_id: 'event-agent-1', status: 'NOT_REQUESTED', request_id: null,
      event_version_hash: null, explanation: null, generated_by: null, fallback_used: null,
      attempt_count: 0, error_code: null, created_at: null, completed_at: null,
    }).status).toBe('NOT_REQUESTED')
  })
})
