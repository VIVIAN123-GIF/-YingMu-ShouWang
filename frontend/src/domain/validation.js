import { EVENT_STATUSES, RISK_DOMAINS, RISK_LEVELS, SOURCE_MODES } from './constants'

export class DataContractError extends Error {
  constructor(message, field = null) {
    super(message)
    this.name = 'DataContractError'
    this.field = field
  }
}

export function assertRiskScore(value, field = 'risk_score', { nullable = false } = {}) {
  if (nullable && value === null) return value
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new DataContractError(`${field} 必须是 0—1 之间的数字`, field)
  }
  return value
}

function assertKnown(value, mapping, field) {
  if (!Object.hasOwn(mapping, value)) throw new DataContractError(`${field} 包含未知枚举：${value}`, field)
}

function assertIsoTime(value, field, { nullable = false } = {}) {
  if (nullable && value === null) return
  const hasTimezone = typeof value === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  if (!hasTimezone || Number.isNaN(Date.parse(value))) {
    throw new DataContractError(`${field} 必须是包含时区的ISO 8601时间`, field)
  }
}

function assertSource(record, label) {
  assertKnown(record?.source_mode, SOURCE_MODES, `${label}.source_mode`)
  if (typeof record?.simulated !== 'boolean') {
    throw new DataContractError(`${label}.simulated 必须是布尔值`, `${label}.simulated`)
  }
}

export function validateEvidence(evidence, index = 0) {
  const label = `evidence[${index}]`
  if (!evidence?.evidence_id) throw new DataContractError(`${label}.evidence_id 缺失`, `${label}.evidence_id`)
  assertIsoTime(evidence.timestamp, `${label}.timestamp`)
  assertKnown(evidence.risk_domain, RISK_DOMAINS, `${label}.risk_domain`)
  if (!Array.isArray(evidence.observation_ids) || evidence.observation_ids.length === 0) {
    throw new DataContractError(`${label}.observation_ids 必须至少包含一个观测ID`, `${label}.observation_ids`)
  }
  ;['severity', 'confidence', 'data_quality'].forEach((field) => assertRiskScore(evidence[field], `${label}.${field}`))
  if (!evidence.asset_id) throw new DataContractError(`${label}.asset_id 缺失`, `${label}.asset_id`)
  if (!evidence.adapter_version) throw new DataContractError(`${label}.adapter_version 缺失`, `${label}.adapter_version`)
  assertSource(evidence, label)
  return evidence
}

export function validateRiskEvent(event) {
  if (!event?.event_id) throw new DataContractError('RiskEvent.event_id 缺失', 'event_id')
  assertKnown(event.risk_level, RISK_LEVELS, 'risk_level')
  assertKnown(event.status, EVENT_STATUSES, 'status')
  assertKnown(event.primary_domain, RISK_DOMAINS, 'primary_domain')
  assertRiskScore(event.risk_score)
  assertIsoTime(event.created_at, 'created_at')
  assertIsoTime(event.updated_at, 'updated_at')
  assertSource(event, 'RiskEvent')
  if (!event.ruleset_version) throw new DataContractError('RiskEvent.ruleset_version 缺失', 'ruleset_version')
  ;(event.evidence_summary || []).forEach(validateEvidence)
  ;(event.interventions || []).forEach((result, index) => {
    assertIsoTime(result.started_at, `interventions[${index}].started_at`)
    assertIsoTime(result.completed_at, `interventions[${index}].completed_at`, { nullable: true })
    assertRiskScore(result.risk_after, `interventions[${index}].risk_after`, { nullable: true })
  })
  ;(event.observations || []).forEach(validateObservation)
  ;(event.risk_history || []).forEach((point, index) => assertRiskScore(point.score, `risk_history[${index}].score`))
  return event
}

export function validateObservation(observation, index = 0) {
  const label = `observations[${index}]`
  if (!observation?.observation_id) throw new DataContractError(`${label}.observation_id 缺失`, `${label}.observation_id`)
  assertIsoTime(observation.timestamp, `${label}.timestamp`)
  ;['confidence', 'data_quality'].forEach((field) => assertRiskScore(observation[field], `${label}.${field}`))
  assertSource(observation, label)
  if (!observation.asset_id) throw new DataContractError(`${label}.asset_id 缺失`, `${label}.asset_id`)
  return observation
}

export function validateEventList(events) {
  if (!Array.isArray(events)) throw new DataContractError('事件列表必须是数组', 'events')
  return events.map(validateRiskEvent)
}

export function validateDashboard(dashboard) {
  assertRiskScore(dashboard?.current_risk?.risk_score, 'current_risk.risk_score')
  assertSource(dashboard?.device, 'device')
  ;(dashboard?.risk_trend || []).forEach((point, index) => assertRiskScore(point.score, `risk_trend[${index}].score`))
  ;(dashboard?.recent_events || []).forEach((event, index) => {
    assertRiskScore(event.risk_score, `recent_events[${index}].risk_score`)
    assertKnown(event.risk_level, RISK_LEVELS, `recent_events[${index}].risk_level`)
    assertKnown(event.status, EVENT_STATUSES, `recent_events[${index}].status`)
    assertSource(event, `recent_events[${index}]`)
  })
  return dashboard
}
