import { DELIVERY_STATUSES, EVENT_STATUSES, RISK_DOMAINS, RISK_LEVELS, SOURCE_MODES } from './constants'

const SCHEMA_VERSION = '1.0'
const TIME_SCALES = new Set(['SHORT', 'MEDIUM', 'LONG'])
const TIME_HORIZONS = new Set(['TREND', 'TODAY', 'IMMINENT'])
const OPERATORS = new Set(['system', 'family', 'staff'])
const ALARM_TASK_STATUSES = new Set(['PENDING', 'PROCESSING', 'WAITING_ALGORITHM', 'RETRY', 'FAILED'])
const AGENT_EXPLANATION_STATUSES = new Set(['NOT_REQUESTED', 'PENDING', 'PROCESSING', 'RETRY', 'SUCCESS', 'FALLBACK', 'FAILED'])
const SUMMARY_FIELDS = new Set(['evidence_id', 'evidence_type', 'explanation'])
const PRE_FALL_FACTORS = new Set([
  'fall_precursor_evidence',
  'personal_baseline_deviation',
  'environment_interaction_risk',
  'data_quality_downgrade',
  'multi_scale_accumulation',
  'normal_fluctuation',
])
const FOREWARNING_ASSESSMENTS = new Set(['VALID', 'PARTIAL', 'INSUFFICIENT'])
const FOREWARNING_ATTENTION_LEVELS = new Set(['UNKNOWN', 'GREEN', 'YELLOW', 'ORANGE'])

export class DataContractError extends Error {
  constructor(message, field = null) {
    super(message)
    this.name = 'DataContractError'
    this.field = field
  }
}

function fail(message, field) {
  throw new DataContractError(message, field)
}

function assertObject(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(`${label} 必须是对象`, label)
  return value
}

function assertRequired(record, field, label) {
  if (!Object.hasOwn(record, field)) fail(`${label}.${field} 缺失`, `${label}.${field}`)
  return record[field]
}

function assertString(value, field, { nullable = false } = {}) {
  if (nullable && value === null) return value
  if (typeof value !== 'string' || value.length === 0) fail(`${field} 必须是非空字符串`, field)
  return value
}

function assertNullableString(value, field) {
  if (value !== null && typeof value !== 'string') fail(`${field} 必须是字符串或 null`, field)
  return value
}

function assertBoolean(value, field) {
  if (typeof value !== 'boolean') fail(`${field} 必须是布尔值`, field)
  return value
}

function assertKnown(value, mapping, field) {
  if (!Object.hasOwn(mapping, value)) fail(`${field} 包含未知枚举：${value}`, field)
  return value
}

function assertOneOf(value, values, field) {
  if (!values.has(value)) fail(`${field} 包含未知枚举：${value}`, field)
  return value
}

function assertSchemaVersion(record, label) {
  if (assertRequired(record, 'schema_version', label) !== SCHEMA_VERSION) {
    fail(`${label}.schema_version 必须为 ${SCHEMA_VERSION}`, `${label}.schema_version`)
  }
}

function assertIsoTime(value, field, { nullable = false } = {}) {
  if (nullable && value === null) return value
  const hasTimezone = typeof value === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  if (!hasTimezone || Number.isNaN(Date.parse(value))) {
    fail(`${field} 必须是包含时区的ISO 8601时间`, field)
  }
  return value
}

function assertRiskValue(value, field) {
  if (value !== null && (typeof value !== 'number' || !Number.isFinite(value))) {
    fail(`${field} 必须是数字或 null`, field)
  }
  return value
}

export function assertRiskScore(value, field = 'risk_score', { nullable = false } = {}) {
  if (nullable && value === null) return value
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) {
    fail(`${field} 必须是 0—1 之间的数字`, field)
  }
  return value
}

function assertScalar(value, field) {
  if (!['string', 'number', 'boolean'].includes(typeof value) || (typeof value === 'number' && !Number.isFinite(value))) {
    fail(`${field} 必须是字符串、数字或布尔值`, field)
  }
  return value
}

function assertSource(record, label) {
  assertKnown(assertRequired(record, 'source_mode', label), SOURCE_MODES, `${label}.source_mode`)
  assertBoolean(assertRequired(record, 'simulated', label), `${label}.simulated`)
}

function assertAssetId(record, label) {
  const value = assertRequired(record, 'asset_id', label)
  if (value !== null && typeof value !== 'string') fail(`${label}.asset_id 必须是字符串或 null`, `${label}.asset_id`)
  return value
}

export function validateEvidenceSummary(summary, index = 0) {
  const label = `evidence_summary[${index}]`
  assertObject(summary, label)
  Object.keys(summary).forEach((field) => {
    if (!SUMMARY_FIELDS.has(field)) fail(`${label} 只能包含摘要字段`, `${label}.${field}`)
  })
  assertString(assertRequired(summary, 'evidence_id', label), `${label}.evidence_id`)
  assertString(assertRequired(summary, 'evidence_type', label), `${label}.evidence_type`)
  assertString(assertRequired(summary, 'explanation', label), `${label}.explanation`)
  return summary
}

export function validateEvidence(evidence, index = 0) {
  const label = `evidence[${index}]`
  assertObject(evidence, label)
  assertSchemaVersion(evidence, label)
  assertString(assertRequired(evidence, 'evidence_id', label), `${label}.evidence_id`)
  const observationIds = assertRequired(evidence, 'observation_ids', label)
  if (!Array.isArray(observationIds) || observationIds.length === 0 || observationIds.some((id) => typeof id !== 'string' || !id)) {
    fail(`${label}.observation_ids 必须是非空字符串数组`, `${label}.observation_ids`)
  }
  assertString(assertRequired(evidence, 'resident_id', label), `${label}.resident_id`)
  assertIsoTime(assertRequired(evidence, 'timestamp', label), `${label}.timestamp`)
  assertKnown(assertRequired(evidence, 'risk_domain', label), RISK_DOMAINS, `${label}.risk_domain`)
  assertString(assertRequired(evidence, 'evidence_type', label), `${label}.evidence_type`)
  ;['severity', 'confidence', 'data_quality'].forEach((field) => assertRiskScore(assertRequired(evidence, field, label), `${label}.${field}`))
  ;['baseline_value', 'current_value', 'baseline_deviation'].forEach((field) => assertRiskValue(assertRequired(evidence, field, label), `${label}.${field}`))
  assertOneOf(assertRequired(evidence, 'time_scale', label), TIME_SCALES, `${label}.time_scale`)
  assertNullableString(assertRequired(evidence, 'location', label), `${label}.location`)
  assertString(assertRequired(evidence, 'explanation', label), `${label}.explanation`)
  assertString(assertRequired(evidence, 'adapter_version', label), `${label}.adapter_version`)
  assertSource(evidence, label)
  return evidence
}

export function validateObservation(observation, index = 0) {
  const label = `observations[${index}]`
  assertObject(observation, label)
  assertSchemaVersion(observation, label)
  assertString(assertRequired(observation, 'observation_id', label), `${label}.observation_id`)
  assertString(assertRequired(observation, 'resident_id', label), `${label}.resident_id`)
  assertIsoTime(assertRequired(observation, 'timestamp', label), `${label}.timestamp`)
  assertString(assertRequired(observation, 'source', label), `${label}.source`)
  assertString(assertRequired(observation, 'feature_name', label), `${label}.feature_name`)
  assertScalar(assertRequired(observation, 'feature_value', label), `${label}.feature_value`)
  assertNullableString(assertRequired(observation, 'unit', label), `${label}.unit`)
  assertNullableString(assertRequired(observation, 'location', label), `${label}.location`)
  assertRiskScore(assertRequired(observation, 'confidence', label), `${label}.confidence`)
  assertRiskScore(assertRequired(observation, 'data_quality', label), `${label}.data_quality`)
  assertAssetId(observation, label)
  assertSource(observation, label)
  return observation
}

export function validateAsset(asset) {
  const label = 'Asset'
  assertObject(asset, label)
  ;['asset_id', 'title', 'fallback_kind', 'verification_status', 'notice']
    .forEach((field) => assertString(assertRequired(asset, field, label), `${label}.${field}`))
  ;['stream_url', 'fallback_url'].forEach((field) =>
    assertNullableString(assertRequired(asset, field, label), `${label}.${field}`))
  assertBoolean(assertRequired(asset, 'available', label), `${label}.available`)
  assertIsoTime(assertRequired(asset, 'captured_at', label), `${label}.captured_at`)
  assertSource(asset, label)
  return asset
}

export function validateInterventionResult(result, index = 0) {
  const label = `interventions[${index}]`
  assertObject(result, label)
  assertSchemaVersion(result, label)
  ;['result_id', 'event_id', 'action_type', 'tool_name'].forEach((field) => assertString(assertRequired(result, field, label), `${label}.${field}`))
  assertIsoTime(assertRequired(result, 'started_at', label), `${label}.started_at`)
  assertIsoTime(assertRequired(result, 'completed_at', label), `${label}.completed_at`, { nullable: true })
  assertOneOf(assertRequired(result, 'delivery_status', label), new Set(Object.keys(DELIVERY_STATUSES)), `${label}.delivery_status`)
  assertNullableString(assertRequired(result, 'resident_response', label), `${label}.resident_response`)
  assertNullableString(assertRequired(result, 'family_feedback', label), `${label}.family_feedback`)
  assertRiskScore(assertRequired(result, 'risk_after', label), `${label}.risk_after`, { nullable: true })
  assertBoolean(assertRequired(result, 'resolved', label), `${label}.resolved`)
  assertNullableString(assertRequired(result, 'resolution_reason', label), `${label}.resolution_reason`)
  assertOneOf(assertRequired(result, 'operator', label), OPERATORS, `${label}.operator`)
  assertSource(result, label)
  return result
}

export function validateRiskEvent(event) {
  const label = 'RiskEvent'
  assertObject(event, label)
  assertSchemaVersion(event, label)
  ;['event_id', 'resident_id', 'recommended_action', 'intervention_policy', 'ruleset_version'].forEach((field) => assertString(assertRequired(event, field, label), `${label}.${field}`))
  assertIsoTime(assertRequired(event, 'created_at', label), `${label}.created_at`)
  assertIsoTime(assertRequired(event, 'updated_at', label), `${label}.updated_at`)
  assertKnown(assertRequired(event, 'primary_domain', label), RISK_DOMAINS, `${label}.primary_domain`)
  const relatedDomains = assertRequired(event, 'related_domains', label)
  if (!Array.isArray(relatedDomains) || relatedDomains.some((domain) => !Object.hasOwn(RISK_DOMAINS, domain))) {
    fail(`${label}.related_domains 必须是风险方向数组`, `${label}.related_domains`)
  }
  assertKnown(assertRequired(event, 'risk_level', label), RISK_LEVELS, `${label}.risk_level`)
  assertRiskScore(assertRequired(event, 'risk_score', label))
  const evidenceIds = assertRequired(event, 'evidence_ids', label)
  if (!Array.isArray(evidenceIds) || evidenceIds.some((id) => typeof id !== 'string' || !id)) fail(`${label}.evidence_ids 必须是字符串数组`, `${label}.evidence_ids`)
  assertOneOf(assertRequired(event, 'time_horizon', label), TIME_HORIZONS, `${label}.time_horizon`)
  assertKnown(assertRequired(event, 'status', label), EVENT_STATUSES, `${label}.status`)
  const summaries = assertRequired(event, 'evidence_summary', label)
  if (!Array.isArray(summaries)) fail(`${label}.evidence_summary 必须是摘要数组`, `${label}.evidence_summary`)
  summaries.forEach(validateEvidenceSummary)
  summaries.forEach((summary, index) => {
    if (!evidenceIds.includes(summary.evidence_id)) {
      fail(`evidence_summary[${index}].evidence_id 不在 RiskEvent.evidence_ids 中`, `evidence_summary[${index}].evidence_id`)
    }
  })
  assertSource(event, label)
  return event
}

export function validateEventViewModel(event) {
  validateRiskEvent(event)
  ;(event.evidences || []).forEach((evidence, index) => {
    validateEvidence(evidence, index)
    if (!event.evidence_ids.includes(evidence.evidence_id)) {
      fail(`evidence[${index}].evidence_id 不在 RiskEvent.evidence_ids 中`, `evidence[${index}].evidence_id`)
    }
  })
  ;(event.observations || []).forEach(validateObservation)
  ;(event.interventions || []).forEach((result, index) => {
    validateInterventionResult(result, index)
    if (result.event_id !== event.event_id) fail(`interventions[${index}].event_id 与 RiskEvent 不一致`, `interventions[${index}].event_id`)
    if (typeof event.simulated === 'boolean' && result.simulated !== event.simulated) {
      fail(`interventions[${index}].simulated 与 RiskEvent 不一致`, `interventions[${index}].simulated`)
    }
  })
  ;(event.risk_history || []).forEach((point, index) => {
    assertObject(point, `risk_history[${index}]`)
    assertString(assertRequired(point, 'time', `risk_history[${index}]`), `risk_history[${index}].time`)
    assertRiskScore(assertRequired(point, 'score', `risk_history[${index}]`), `risk_history[${index}].score`)
  })
  return event
}

export function validateEventList(events) {
  if (!Array.isArray(events)) fail('事件列表必须是数组', 'events')
  return events.map(validateEventViewModel)
}

export function validateDeviceStatus(device) {
  const label = 'DeviceStatus'
  assertObject(device, label)
  assertBoolean(assertRequired(device, 'online', label), `${label}.online`)
  assertOneOf(assertRequired(device, 'adapter_mode', label), new Set(['EZVIZ_CLOUD', 'RECORDED_REPLAY']), `${label}.adapter_mode`)
  assertOneOf(assertRequired(device, 'source_mode', label), new Set(['LIVE_DEVICE', 'RECORDED_REPLAY']), `${label}.source_mode`)
  assertString(assertRequired(device, 'device_alias', label), `${label}.device_alias`)
  assertBoolean(assertRequired(device, 'simulated', label), `${label}.simulated`)
  assertBoolean(assertRequired(device, 'collection_active', label), `${label}.collection_active`)
  return device
}

export function validateAlarmProcessingTask(task, index = 0) {
  const label = `alarm_processing[${index}]`
  assertObject(task, label)
  ;['task_id', 'alarm_ref', 'resident_id', 'device_ref', 'available_at', 'create_time', 'update_time']
    .forEach((field) => assertString(assertRequired(task, field, label), `${label}.${field}`))
  assertOneOf(assertRequired(task, 'status', label), ALARM_TASK_STATUSES, `${label}.status`)
  ;['attempt_count', 'max_attempts'].forEach((field) => {
    const value = assertRequired(task, field, label)
    if (!Number.isInteger(value) || value < 0) fail(`${label}.${field} 必须是非负整数`, `${label}.${field}`)
  })
  ;['capture_asset_id', 'error_code', 'error_message', 'started_at', 'finished_at'].forEach((field) =>
    assertNullableString(assertRequired(task, field, label), `${label}.${field}`))
  return task
}

export function validateAlarmProcessingTasks(tasks) {
  if (!Array.isArray(tasks)) fail('告警处理任务必须是数组', 'alarm_processing')
  return tasks.map(validateAlarmProcessingTask)
}

export function validateRiskReview(review, index = 0) {
  const label = `risk_reviews[${index}]`
  assertObject(review, label)
  if (assertRequired(review, 'schema_version', label) !== 'risk-review/1.0') {
    fail(`${label}.schema_version 必须为 risk-review/1.0`, `${label}.schema_version`)
  }
  ;['trace_id', 'resident_id', 'evidence_id', 'evidence_type', 'explanation', 'matched_rule', 'ruleset_version']
    .forEach((field) => assertString(assertRequired(review, field, label), `${label}.${field}`))
  assertIsoTime(assertRequired(review, 'evaluated_at', label), `${label}.evaluated_at`)
  assertOneOf(assertRequired(review, 'risk_level', label), new Set(['UNKNOWN', 'YELLOW']), `${label}.risk_level`)
  assertKnown(assertRequired(review, 'source_mode', label), SOURCE_MODES, `${label}.source_mode`)
  assertBoolean(assertRequired(review, 'simulated', label), `${label}.simulated`)
  if (assertRequired(review, 'review_required', label) !== true) {
    fail(`${label}.review_required 必须为 true`, `${label}.review_required`)
  }
  return review
}

export function validateRiskReviews(reviews) {
  if (!Array.isArray(reviews)) fail('人工复核队列必须是数组', 'risk_reviews')
  return reviews.map(validateRiskReview)
}

export function validateAgentExplanationJob(job) {
  const label = 'AgentExplanation'
  assertObject(job, label)
  assertString(assertRequired(job, 'event_id', label), `${label}.event_id`)
  assertOneOf(assertRequired(job, 'status', label), AGENT_EXPLANATION_STATUSES, `${label}.status`)
  ;['request_id', 'event_version_hash', 'generated_by', 'error_code', 'created_at', 'completed_at']
    .forEach((field) => assertNullableString(assertRequired(job, field, label), `${label}.${field}`))
  const attemptCount = assertRequired(job, 'attempt_count', label)
  if (!Number.isInteger(attemptCount) || attemptCount < 0) fail(`${label}.attempt_count must be a non-negative integer`, `${label}.attempt_count`)
  const fallbackUsed = assertRequired(job, 'fallback_used', label)
  if (fallbackUsed !== null && typeof fallbackUsed !== 'boolean') fail(`${label}.fallback_used must be boolean or null`, `${label}.fallback_used`)
  const explanation = assertRequired(job, 'explanation', label)
  if (explanation === null) {
    if (['SUCCESS', 'FALLBACK'].includes(job.status)) fail(`${label}.explanation is required for completed status`, `${label}.explanation`)
    return {
      event_id: job.event_id,
      status: job.status,
      explanation: null,
      attempt_count: job.attempt_count,
      created_at: job.created_at,
      completed_at: job.completed_at,
    }
  }
  assertObject(explanation, `${label}.explanation`)
  if (explanation.schema_version !== 'agent-explanation/1.0') fail(`${label}.explanation.schema_version is invalid`, `${label}.explanation.schema_version`)
  ;['request_id', 'event_id', 'summary', 'recommended_action_text', 'capability_notice', 'generated_by']
    .forEach((field) => assertString(assertRequired(explanation, field, `${label}.explanation`), `${label}.explanation.${field}`))
  const points = assertRequired(explanation, 'reasoning_points', `${label}.explanation`)
  if (!Array.isArray(points) || points.length === 0 || points.some((point) => typeof point !== 'string' || point.length === 0)) {
    fail(`${label}.explanation.reasoning_points must be a non-empty string array`, `${label}.explanation.reasoning_points`)
  }
  assertBoolean(assertRequired(explanation, 'fallback_used', `${label}.explanation`), `${label}.explanation.fallback_used`)
  if (fallbackUsed !== null) assertBoolean(fallbackUsed, `${label}.fallback_used`)
  return {
    event_id: job.event_id,
    status: job.status,
    explanation: {
      summary: explanation.summary,
      reasoning_points: [...explanation.reasoning_points],
      recommended_action_text: explanation.recommended_action_text,
      capability_notice: explanation.capability_notice,
      generated_by: explanation.generated_by,
      fallback_used: explanation.fallback_used,
    },
    attempt_count: job.attempt_count,
    created_at: job.created_at,
    completed_at: job.completed_at,
  }
}

export function validateDashboard(dashboard) {
  if (dashboard?.current_risk) assertRiskScore(dashboard.current_risk.risk_score, 'current_risk.risk_score')
  assertSource(dashboard?.device, 'device')
  ;(dashboard?.risk_trend || []).forEach((point, index) => assertRiskScore(point.score, `risk_trend[${index}].score`))
  if (dashboard?.pre_fall_summary) {
    const summary = assertObject(dashboard.pre_fall_summary, 'pre_fall_summary')
    assertOneOf(assertRequired(summary, 'risk_level', 'pre_fall_summary'), FOREWARNING_ATTENTION_LEVELS, 'pre_fall_summary.risk_level')
    ;['instant_risk', 'risk_30s', 'trend_3min', 'personal_deviation', 'environment_risk', 'quality_penalty']
      .forEach((field) => assertRiskScore(assertRequired(summary, field, 'pre_fall_summary'), `pre_fall_summary.${field}`))
    assertOneOf(assertRequired(summary, 'trend_direction', 'pre_fall_summary'), new Set(['RISING', 'STABLE', 'FALLING']), 'pre_fall_summary.trend_direction')
    const factors = assertRequired(summary, 'dominant_factors', 'pre_fall_summary')
    if (!Array.isArray(factors) || factors.some((factor) => !PRE_FALL_FACTORS.has(factor))) {
      fail('pre_fall_summary.dominant_factors 包含未知项', 'pre_fall_summary.dominant_factors')
    }
    const evidenceIds = assertRequired(summary, 'evidence_ids', 'pre_fall_summary')
    if (!Array.isArray(evidenceIds) || evidenceIds.some((id) => typeof id !== 'string' || !id)) {
      fail('pre_fall_summary.evidence_ids 必须是字符串数组', 'pre_fall_summary.evidence_ids')
    }
    assertString(assertRequired(summary, 'recommended_intervention', 'pre_fall_summary'), 'pre_fall_summary.recommended_intervention')
  }
  ;(dashboard?.recent_events || []).forEach((event, index) => {
    assertRiskScore(event.risk_score, `recent_events[${index}].risk_score`)
    assertKnown(event.risk_level, RISK_LEVELS, `recent_events[${index}].risk_level`)
    assertKnown(event.status, EVENT_STATUSES, `recent_events[${index}].status`)
    if (event.source_mode !== undefined || event.simulated !== undefined) assertSource(event, `recent_events[${index}]`)
    ;(event.evidence_summary || []).forEach(validateEvidenceSummary)
  })
  return dashboard
}

export function validateForewarningSnapshot(snapshot, label = 'forewarning') {
  const value = assertObject(snapshot, label)
  if (value.schema_version !== 'forewarning-snapshot/1.0') fail(`${label}.schema_version 无效`, `${label}.schema_version`)
  assertString(assertRequired(value, 'snapshot_id', label), `${label}.snapshot_id`)
  assertOneOf(assertRequired(value, 'assessment_status', label), FOREWARNING_ASSESSMENTS, `${label}.assessment_status`)
  assertOneOf(assertRequired(value, 'confidence_level', label), new Set(['LOW', 'MEDIUM', 'HIGH']), `${label}.confidence_level`)
  assertOneOf(assertRequired(value, 'baseline_status', label), new Set(['INSUFFICIENT', 'PROVISIONAL', 'STABLE']), `${label}.baseline_status`)
  const components = assertObject(assertRequired(value, 'components', label), `${label}.components`)
  ;['human_risk', 'environment_risk', 'interaction_risk'].forEach((field) => assertRiskScore(assertRequired(components, field, `${label}.components`), `${label}.components.${field}`))
  if (components.personal_deviation !== null) assertRiskScore(components.personal_deviation, `${label}.components.personal_deviation`)
  ;['instant', 'short_30s', 'trend_3min'].forEach((field) => {
    const horizon = assertObject(assertRequired(value, field, label), `${label}.${field}`)
    assertRiskScore(assertRequired(horizon, 'engineering_index', `${label}.${field}`), `${label}.${field}.engineering_index`)
    assertOneOf(assertRequired(horizon, 'attention_level', `${label}.${field}`), FOREWARNING_ATTENTION_LEVELS, `${label}.${field}.attention_level`)
  })
  return value
}
