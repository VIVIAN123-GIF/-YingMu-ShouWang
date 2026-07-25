import { describe, expect, it } from 'vitest'
import events from '../mocks/events.json'
import dashboard from '../mocks/dashboard.json'
import observations from '../mocks/observations.json'
import fourObjects from '../../contracts/v1/examples/four-objects.json'
import {
  DataContractError,
  validateDashboard,
  validateEvidence,
  validateInterventionResult,
  validateObservation,
  validateRiskEvent,
  validateEventViewModel,
} from '../domain/validation'
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
      expect(() => validateEventViewModel(event)).not.toThrow()
    })
    expect(() => validateDashboard(dashboard)).not.toThrow()
  })

  it('校验冻结四对象样例、摘要结构和 Observation 可空 asset_id', () => {
    expect(() => validateObservation(fourObjects.observation)).not.toThrow()
    expect(() => validateEvidence(fourObjects.evidence)).not.toThrow()
    expect(() => validateRiskEvent(fourObjects.risk_event)).not.toThrow()
    expect(() => validateInterventionResult(fourObjects.intervention_result)).not.toThrow()
    expect(fourObjects.observation.asset_id).toBeNull()
    expect(fourObjects.evidence).not.toHaveProperty('asset_id')
    expect(Object.keys(fourObjects.risk_event.evidence_summary[0]).sort()).toEqual([
      'evidence_id', 'evidence_type', 'explanation',
    ])
    expect(fourObjects.intervention_result.source_mode).toBe('MOCK')
    expect(fourObjects.intervention_result.simulated).toBe(true)
    expect(fourObjects.risk_event.source_mode).toBe('MOCK')
    expect(fourObjects.risk_event.simulated).toBe(true)
  })

  it('Evidence 只通过 observation_ids 追溯 Observation.asset_id', () => {
    const observationsById = new Map(observations.map((observation) => [observation.observation_id, observation]))
    events.flatMap((event) => event.evidences || []).forEach((evidence) => {
      expect(evidence).not.toHaveProperty('asset_id')
      evidence.observation_ids.forEach((observationId) => {
        expect(observationsById.has(observationId)).toBe(true)
        expect(observationsById.get(observationId)).toHaveProperty('asset_id')
      })
    })
  })

  it('拒绝把完整 Evidence 放进 evidence_summary', () => {
    const invalid = structuredClone(fourObjects.risk_event)
    invalid.evidence_summary[0].confidence = 0.9
    expect(() => validateRiskEvent(invalid)).toThrow(DataContractError)
  })

  it('拒绝四对象缺少冻结必填字段', () => {
    const cases = [
      [validateObservation, 'observation', 'schema_version'],
      [validateEvidence, 'evidence', 'resident_id'],
      [validateEvidence, 'evidence', 'adapter_version'],
      [validateEvidence, 'evidence', 'time_scale'],
      [validateRiskEvent, 'risk_event', 'ruleset_version'],
      [validateInterventionResult, 'intervention_result', 'delivery_status'],
      [validateInterventionResult, 'intervention_result', 'operator'],
      [validateInterventionResult, 'intervention_result', 'simulated'],
    ]
    cases.forEach(([validate, objectName, field]) => {
      const invalid = structuredClone(fourObjects[objectName])
      delete invalid[field]
      expect(() => validate(invalid)).toThrow(DataContractError)
    })
  })

  it.each(['source_mode', 'simulated'])('拒绝 RiskEvent 缺少来源字段 %s', (field) => {
    const invalid = structuredClone(fourObjects.risk_event)
    delete invalid[field]
    expect(() => validateRiskEvent(invalid)).toThrow(DataContractError)
  })

  it('拒绝 ViewModel 中与 RiskEvent 不一致的干预模拟标记', () => {
    const viewModel = {
      ...structuredClone(fourObjects.risk_event),
      source_mode: 'MOCK',
      simulated: true,
      evidences: [structuredClone(fourObjects.evidence)],
      observations: [structuredClone(fourObjects.observation)],
      interventions: [structuredClone(fourObjects.intervention_result)],
    }
    expect(() => validateEventViewModel(viewModel)).not.toThrow()
    viewModel.interventions[0].simulated = false
    expect(() => validateEventViewModel(viewModel)).toThrow(DataContractError)
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
