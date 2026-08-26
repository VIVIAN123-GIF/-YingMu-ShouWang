import axios from 'axios'
import { reactive } from 'vue'
import dashboardReplay from '../replay-data/dashboard.json'
import eventsReplay from '../replay-data/events.json'
import weeklyReplay from '../replay-data/weekly.json'
import deviceReplay from '../replay-data/device.json'
import observationsReplay from '../replay-data/observations.json'
import baselineReplay from '../replay-data/baseline.json'
import forewarningReplay from '../replay-data/forewarning.json'
import assetsReplay from '../replay-data/assets.json'
import explanationsReplay from '../replay-data/explanations.json'
import { DATA_MODES } from '../domain/constants'
import {
  validateAgentExplanationJob, validateAlarmProcessingTasks, validateAsset, validateDashboard, validateDeviceStatus, validateEventList, validateEventViewModel, validateForewarningSnapshot, validateInterventionResult, validateRiskReviews,
} from '../domain/validation'
import {
  normalizeBaseline, normalizeDashboard, normalizeDevice, normalizeEvent, normalizeWeeklyReport,
} from './viewModel'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const RESIDENT_ID = import.meta.env.VITE_RESIDENT_ID || 'resident-001'
const PAGES_BUILD = import.meta.env.VITE_PAGES_BUILD === 'true'
const AUTHORIZED_CLIP_URL = import.meta.env.VITE_AUTHORIZED_CLIP_URL?.trim() || ''
// API is the safe default; offline replay is an explicit, traceable dataset.
const configuredMode = import.meta.env.VITE_DATA_MODE || 'api'
const initialMode = PAGES_BUILD ? 'replay' : (sessionStorage.getItem('yingmu-data-mode') || configuredMode)

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  // Device status may require a round trip to the live provider; keep the
  // dashboard from failing while the other API calls are still healthy.
  timeout: 8000,
  headers: { Accept: 'application/json', 'Content-Type': 'application/json; charset=utf-8' },
})

export function normalizeApiError(error) {
  const body = error?.response?.data
  const detail = body?.error || body?.detail
  if (detail && typeof detail === 'object') {
    const requestId = detail.request_id || body?.request_id
    const message = detail.message || error.message
    error.api = { code: detail.code || 'API_ERROR', message, request_id: requestId || null }
    error.message = `${message}${requestId ? ` (request_id: ${requestId})` : ''}`
  }
  return error
}

apiClient.interceptors.response.use((response) => response, (error) => Promise.reject(normalizeApiError(error)))

const replayData = {
  dashboard: structuredClone(dashboardReplay),
  events: structuredClone(eventsReplay),
  weekly: structuredClone(weeklyReplay),
  device: structuredClone(deviceReplay),
  observations: structuredClone(observationsReplay),
  baseline: structuredClone(baselineReplay),
  forewarning: structuredClone(forewarningReplay),
  assets: structuredClone(assetsReplay),
  explanations: structuredClone(explanationsReplay),
}

const requiredReplayAssets = Object.freeze({
  'asset-fall-authorized': '/media/fall-risk-replay.mp4',
  'asset-mental-week': '/media/activity-route-replay-browser.mp4',
  'asset-green-daily': '/media/daily-baseline-replay-browser.mp4',
})

export function validateReplayAssetManifest() {
  const issues = Object.entries(requiredReplayAssets).flatMap(([assetId, fallbackUrl]) => {
    const asset = replayData.assets.find((item) => item.asset_id === assetId)
    if (!asset) return [`缺少授权资产 ${assetId}`]
    return asset.fallback_url !== fallbackUrl
      ? [`授权资产 ${assetId} 未映射到 ${fallbackUrl}`]
      : []
  })
  if (issues.length && typeof console !== 'undefined') console.error(`[授权回放素材校验] ${issues.join('；')}`)
  return issues
}

validateReplayAssetManifest()

const feedbackCache = new Map()
const interventionResultCache = new Map()
const assetRequestCache = new Map()
const submittedFeedbackSession = new Set()
const FEEDBACK_STORAGE_KEY = 'yingmu-feedback-records-v1'
const FEEDBACK_KINDS = new Set(['CARE', 'IDENTITY_VERIFICATION'])

// 回放反馈仅用于当前演示页面，重新打开网址时从空白状态开始。
if (initialMode === 'replay' || PAGES_BUILD) {
  try { localStorage.removeItem(FEEDBACK_STORAGE_KEY) } catch { /* Storage may be unavailable. */ }
}

function readFeedbackRecords() {
  try {
    const value = JSON.parse(localStorage.getItem(FEEDBACK_STORAGE_KEY) || '[]')
    return Array.isArray(value) ? value : []
  } catch { return [] }
}

function writeFeedbackRecords(records) {
  try { localStorage.setItem(FEEDBACK_STORAGE_KEY, JSON.stringify(records.slice(-100))) } catch { /* Storage may be unavailable. */ }
}

function replayContext() {
  return runtime.mode === 'replay' || runtime.activeSource === 'replay_dataset'
}

function feedbackRecordId(eventId, feedbackKind, value) {
  return stableFeedbackId(eventId, { feedback_kind: feedbackKind, value })
}

function normalizeFeedbackRecord(record, defaults = {}) {
  return {
    feedback_id: record.feedback_id,
    event_id: record.event_id,
    feedback_kind: record.feedback_kind || defaults.feedback_kind || 'CARE',
    value: record.value || '',
    operator: record.operator || 'family',
    recorded_at: record.recorded_at || record.updated_at || new Date().toISOString(),
    source_mode: record.source_mode || defaults.source_mode || 'RECORDED_REPLAY',
    simulated: record.simulated ?? defaults.simulated ?? true,
    saved_in_demo: record.saved_in_demo ?? defaults.saved_in_demo ?? true,
  }
}

export function getRecordedFeedback(eventId = null) {
  if (!replayContext()) return []
  const records = readFeedbackRecords()
  return structuredClone(eventId ? records.filter((record) => record.event_id === eventId) : records)
}

export function getAllRecordedFeedback() {
  return getRecordedFeedback()
}

export function clearRecordedFeedback() {
  try { localStorage.removeItem(FEEDBACK_STORAGE_KEY) } catch { /* Storage may be unavailable. */ }
  feedbackCache.clear()
  submittedFeedbackSession.clear()
}

function saveReplayFeedback(record) {
  const records = readFeedbackRecords().filter((item) => item.feedback_id !== record.feedback_id)
  records.push(record)
  writeFeedbackRecords(records)
  return record
}

export const runtime = reactive({
  mode: DATA_MODES[initialMode] ? initialMode : 'auto',
  activeSource: initialMode === 'replay' ? 'replay_dataset' : 'api',
  degraded: false,
  message: initialMode === 'replay' ? '当前使用离线授权回放数据集' : '',
  apiBaseUrl: API_BASE_URL,
  lastError: null,
})

const storedAudit = (() => {
  try { return JSON.parse(sessionStorage.getItem('yingmu-audit-log') || '[]') }
  catch { return [] }
})()
export const auditLog = reactive(Array.isArray(storedAudit) ? storedAudit : [])

function redact(value) {
  return String(value || '')
    .replace(/https?:\/\/[^\s]+/gi, '[URL_REDACTED]')
    .replace(/(token|secret|password|accesskey)\s*[=:]\s*[^\s,;]+/gi, '$1=[REDACTED]')
    .slice(0, 300)
}

function recordAudit(operation, status, details = {}) {
  const entry = {
    timestamp: new Date().toISOString(),
    operation,
    status,
    mode: runtime.mode,
    active_source: runtime.activeSource,
    event_id: details.event_id || null,
    ruleset_version: details.ruleset_version || null,
    detail: redact(details.detail),
  }
  auditLog.push(entry)
  if (auditLog.length > 200) auditLog.shift()
  sessionStorage.setItem('yingmu-audit-log', JSON.stringify(auditLog))
  return entry
}

export function exportAuditLog() {
  return JSON.parse(JSON.stringify([...auditLog]))
}

if (typeof window !== 'undefined') {
  window.__YINGMU_AUDIT__ = { export: exportAuditLog }
}

export function setDataMode(mode) {
  if (PAGES_BUILD && mode !== 'replay') return
  if (!DATA_MODES[mode]) return
  runtime.mode = mode
  runtime.activeSource = mode === 'replay' ? 'replay_dataset' : 'api'
  runtime.degraded = false
  runtime.lastError = null
  runtime.message = mode === 'replay' ? '当前使用离线授权回放数据集' : ''
  sessionStorage.setItem('yingmu-data-mode', mode)
  recordAudit('data-mode.change', 'SUCCESS', { detail: `mode=${mode}` })
}

function payload(response) {
  return response?.data?.data ?? response?.data
}

function shouldFallback(error) {
  if (error?.name === 'DataContractError') return false
  const status = error?.response?.status
  return !error?.response || status === 404 || status === 501 || status >= 500
}

async function resolveData(operation, apiRequest, replayFactory, validate = (value) => value) {
  if (runtime.mode === 'replay') {
    runtime.activeSource = 'replay_dataset'
    runtime.degraded = false
    const result = validate(structuredClone(replayFactory()))
    recordAudit(operation, 'REPLAY', { detail: 'authorized-replay-dataset', event_id: result?.event_id, ruleset_version: result?.ruleset_version })
    return result
  }

  try {
    const result = validate(await apiRequest())
    runtime.activeSource = 'api'
    runtime.degraded = false
    runtime.message = ''
    runtime.lastError = null
    recordAudit(operation, 'SUCCESS', { detail: 'fastapi', event_id: result?.event_id, ruleset_version: result?.ruleset_version })
    return result
  } catch (error) {
    runtime.lastError = error?.message || 'FastAPI 请求失败'
    if (runtime.mode === 'auto' && shouldFallback(error)) {
      runtime.activeSource = 'replay_dataset'
      runtime.degraded = true
      runtime.message = 'FastAPI 暂不可用，已切换离线授权回放数据集'
      const result = validate(structuredClone(replayFactory()))
      recordAudit(operation, 'DEGRADED_REPLAY', { detail: error?.message || 'FastAPI unavailable', event_id: result?.event_id, ruleset_version: result?.ruleset_version })
      return result
    }
    recordAudit(operation, 'FAILED', { detail: error?.message || 'contract/api error' })
    throw error
  }
}

function listFrom(data) {
  if (Array.isArray(data)) return data
  return data?.items || data?.events || []
}

function observationsFor(event) {
  const ids = new Set((event.evidences || []).flatMap((evidence) => evidence.observation_ids || []))
  return replayData.observations.filter((observation) => ids.has(observation.observation_id))
}

function hydrateReplayEvent(event) {
  return { ...event, observations: observationsFor(event) }
}

function replayForewarningFor(eventId) {
  return replayData.forewarning
    .filter((snapshot) => snapshot.event_id === eventId)
    .map((snapshot, index) => validateForewarningSnapshot(snapshot, `forewarning[${index}]`))
}

export async function getDashboard(residentId = RESIDENT_ID) {
  return resolveData('dashboard.read', async () => {
    const [eventsResponse, deviceResponse, baselineResponse] = await Promise.all([
      apiClient.get('/events', { params: { resident_id: residentId } }),
      apiClient.get('/device/status'),
      apiClient.get(`/residents/${encodeURIComponent(residentId)}/baseline`),
    ])
    const events = validateEventList(listFrom(payload(eventsResponse)))
    const baseline = payload(baselineResponse)
    return normalizeDashboard({ events, device: validateDeviceStatus(payload(deviceResponse)), baseline, residentId })
  }, () => normalizeDashboard({
    events: replayData.events,
    device: validateDeviceStatus(replayData.device),
    baseline: {
      ...replayData.baseline,
      today: {
        ...replayData.baseline.today,
        care_status: getRecordedFeedback().filter((record) => record.feedback_kind === 'CARE').at(-1)?.value
          || replayData.baseline.today.care_status,
      },
    },
    residentId,
  }), validateDashboard)
}

export async function getEvents(residentId = RESIDENT_ID) {
  return resolveData('events.list', async () => {
    const response = await apiClient.get('/events', { params: { resident_id: residentId } })
    return validateEventList(listFrom(payload(response))).map(normalizeEvent)
  }, () => replayData.events.map(normalizeEvent), validateEventList)
}

export async function getRiskReviews(residentId = RESIDENT_ID, limit = 20) {
  return resolveData('risk-reviews.list', async () => {
    const response = await apiClient.get('/risk/reviews', { params: { resident_id: residentId, limit } })
    return validateRiskReviews(listFrom(payload(response)))
  }, () => [], validateRiskReviews)
}

export async function getEvent(eventId) {
  return resolveData('event.detail', async () => {
    const [eventResponse, snapshotResponse] = await Promise.all([
      apiClient.get(`/events/${eventId}`),
      apiClient.get(`/events/${encodeURIComponent(eventId)}/forewarning`),
    ])
    const event = payload(eventResponse)
    validateEventViewModel(event)
    const snapshots = listFrom(payload(snapshotResponse)).map((snapshot, index) => validateForewarningSnapshot(snapshot, `forewarning[${index}]`))
    return normalizeEvent({ ...event, forewarning_snapshots: snapshots, feedback_records: getRecordedFeedback(event.event_id) })
  }, () => normalizeEvent({
    ...hydrateReplayEvent(replayData.events.find((event) => event.event_id === eventId) || replayData.events[0]),
    feedback_records: getRecordedFeedback(eventId),
    forewarning_snapshots: replayForewarningFor(eventId),
  }), validateEventViewModel)
}

export async function getEventForewarning(eventId) {
  return resolveData('event.forewarning', async () => {
    const snapshots = listFrom(payload(await apiClient.get(`/events/${encodeURIComponent(eventId)}/forewarning`)))
    return snapshots.map((snapshot, index) => validateForewarningSnapshot(snapshot, `forewarning[${index}]`))
  }, () => replayForewarningFor(eventId))
}

function replayTimePlusSeconds(value, seconds) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  const beijingMillis = date.getTime() + (seconds * 1000) + (8 * 60 * 60 * 1000)
  return `${new Date(beijingMillis).toISOString().slice(0, 19)}+08:00`
}

export function getReplayExplanation(eventId) {
  const template = replayData.explanations[eventId]
  if (!template) throw new Error('本地回放解释不可用')
  const createdAtSource = replayData.events.find((event) => event.event_id === eventId)?.created_at || null
  const createdAt = replayTimePlusSeconds(createdAtSource, 0)
  return validateAgentExplanationJob({ event_id: eventId, status: 'FALLBACK', request_id: `replay-${eventId}`, event_version_hash: 'replay-explanation-v1', generated_by: 'replay-explanation-v1', fallback_used: true, attempt_count: 1, error_code: null, created_at: createdAt, completed_at: replayTimePlusSeconds(createdAtSource, 5), explanation: { schema_version: 'agent-explanation/1.0', request_id: `replay-${eventId}`, event_id: eventId, ...template, capability_notice: 'RECORDED_REPLAY / 授权回放', generated_by: 'replay-explanation-v1', fallback_used: true } })
}

export async function getEventExplanation(eventId) {
  if (runtime.mode === 'replay') {
    const result = getReplayExplanation(eventId)
    recordAudit('event.explanation.read', 'REPLAY', { event_id: eventId, detail: 'authorized-replay-dataset' })
    return result
  }
  if (PAGES_BUILD) {
    return getReplayExplanation(eventId)
    /* legacy static template retained below for compatibility */
    const result = validateAgentExplanationJob({
      event_id: eventId,
      status: 'FALLBACK',
      request_id: `static-${eventId}`,
      event_version_hash: 'static-pages-v1',
      generated_by: 'static-demo',
      fallback_used: true,
      attempt_count: 1,
      error_code: null,
      created_at: null,
      completed_at: null,
      explanation: {
        schema_version: 'agent-explanation/1.0',
        request_id: `static-${eventId}`,
        event_id: eventId,
        summary: '基于固定 Evidence 的脱敏解释',
        reasoning_points: ['当前页面仅回放预置证据，不连接后端或外部模型。'],
        recommended_action_text: '按演示事件中的分级干预流程继续查看。',
        capability_notice: 'RECORDED_REPLAY / 授权回放，仅用于赛事评审走查。',
        generated_by: 'static-demo',
        fallback_used: true,
      },
    })
    recordAudit('event.explanation.read', 'REPLAY', { event_id: eventId, detail: 'authorized-replay-dataset' })
    return result
  }
  try {
    const result = validateAgentExplanationJob(payload(await apiClient.get(
      `/events/${encodeURIComponent(eventId)}/explanation`,
    )))
    recordAudit('event.explanation.read', 'SUCCESS', {
      event_id: result.event_id,
      detail: `status=${result.status}`,
    })
    return result
  } catch (error) {
    if (runtime.mode === 'auto' && shouldFallback(error) && replayData.explanations[eventId]) {
      runtime.activeSource = 'replay_dataset'
      runtime.degraded = true
      recordAudit('event.explanation.read', 'DEGRADED_REPLAY', { event_id: eventId, detail: 'FastAPI unavailable' })
      return getReplayExplanation(eventId)
    }
    recordAudit('event.explanation.read', 'FAILED', {
      event_id: eventId,
      detail: 'explanation-read-failed',
    })
    throw error
  }
}

export async function interveneEvent(eventId) {
  const encodedEventId = encodeURIComponent(eventId)
  if (runtime.mode !== 'replay') {
    try {
      const result = validateInterventionResult(payload(await apiClient.post(
        `/events/${encodedEventId}/intervene`, null,
        { headers: { 'Content-Type': 'application/json; charset=utf-8' } },
      )))
      runtime.activeSource = 'api'
      runtime.degraded = false
      runtime.message = ''
      recordAudit('intervention.trigger', 'SUCCESS', { event_id: eventId, detail: result.result_id })
      return result
    } catch (error) {
      if (!(runtime.mode === 'auto' && shouldFallback(error))) {
        recordAudit('intervention.trigger', 'FAILED', { event_id: eventId, detail: error?.message })
        throw error
      }
      runtime.activeSource = 'replay_dataset'
      runtime.degraded = true
      runtime.message = '后端干预接口暂不可用，本次仅展示离线授权回放结果'
      recordAudit('intervention.trigger', 'DEGRADED', { event_id: eventId, detail: error?.message })
    }
  }

  const timestamp = new Date().toISOString()
  const result = validateInterventionResult({
    schema_version: '1.0',
    result_id: `result-${eventId}-replay-intervention`,
    event_id: eventId,
    started_at: timestamp,
    completed_at: timestamp,
    action_type: 'voice',
    tool_name: 'offline_replay_intervention',
    delivery_status: 'SUCCESS',
    resident_response: null,
    family_feedback: null,
    risk_after: null,
    resolved: false,
    resolution_reason: 'Declared offline replay fallback',
    operator: 'system',
    source_mode: 'RECORDED_REPLAY',
    simulated: true,
  })
  recordAudit('intervention.trigger', 'REPLAY', { event_id: eventId, detail: result.result_id })
  return result
}

export async function getWeeklyReport(residentId = RESIDENT_ID) {
  const report = await resolveData('reports.weekly', async () => normalizeWeeklyReport(payload(await apiClient.get(
    '/reports/weekly', { params: { resident_id: residentId } },
  ))), () => normalizeWeeklyReport(replayData.weekly))
  if (!replayContext()) return report
  const records = getRecordedFeedback()
  const careRecord = records.filter((record) => record.feedback_kind === 'CARE').at(-1)
  const identityRecord = records.filter((record) => record.feedback_kind === 'IDENTITY_VERIFICATION').at(-1)
  return {
    ...report,
    care: careRecord || submittedFeedbackSession.has(`${report.care?.event_id}:CARE`)
      ? { ...report.care, status: submittedFeedbackSession.has(`${report.care?.event_id}:CARE`) ? 'SUBMITTED' : report.care.status, feedback_record: careRecord }
      : report.care,
    visitor_case: identityRecord && report.visitor_case
      ? { ...report.visitor_case, verification_status: submittedFeedbackSession.has(`${report.visitor_case.event_id}:IDENTITY_VERIFICATION`) ? 'SUBMITTED' : report.visitor_case.verification_status, feedback_record: identityRecord }
      : report.visitor_case,
  }
}

export async function getAsset(assetId) {
  if (!assetId) return null

  const cacheKey = `${runtime.mode}:${assetId}`
  if (assetRequestCache.has(cacheKey)) return assetRequestCache.get(cacheKey)

  function readReplayAsset() {
    const configuredAsset = replayData.assets.find((asset) => asset.asset_id === assetId)
    const configuredUrl = assetId === 'asset-fall-authorized' && AUTHORIZED_CLIP_URL
      ? AUTHORIZED_CLIP_URL
      : configuredAsset?.fallback_url
    const result = validateAsset(configuredAsset ? {
      ...structuredClone(configuredAsset),
      fallback_url: configuredUrl || null,
      available: Boolean(configuredUrl),
      verification_status: configuredUrl ? 'AUTHORIZED_LOCAL_CLIP' : configuredAsset.verification_status,
      notice: assetId === 'asset-fall-authorized' && AUTHORIZED_CLIP_URL
        ? '已配置授权的本地模拟实验回放片段。'
        : configuredAsset.notice,
    } : {
      asset_id: assetId,
      title: '授权回放数据集素材',
      source_mode: 'RECORDED_REPLAY',
      simulated: true,
      stream_url: null,
      fallback_url: null,
      fallback_kind: 'unavailable',
      available: false,
      verification_status: 'AUTHORIZED_LOCAL_CLIP',
      captured_at: new Date().toISOString(),
      notice: `固定演示数据仅保留素材标识（${assetId}）`,
    })
    recordAudit('asset.read', 'REPLAY', { detail: assetId })
    assetRequestCache.set(cacheKey, Promise.resolve(result))
    return result
  }

  if (runtime.mode === 'replay') return readReplayAsset()

  const request = (async () => {
    try {
      const result = validateAsset(payload(await apiClient.get(`/assets/${encodeURIComponent(assetId)}`)))
      recordAudit('asset.read', 'SUCCESS', { detail: assetId })
      return result
    } catch (error) {
      if (runtime.mode === 'auto' && shouldFallback(error)) {
        runtime.activeSource = 'replay_dataset'
        runtime.degraded = true
        runtime.message = '素材接口暂不可用，已切换对应的离线授权回放素材'
        const result = readReplayAsset()
        recordAudit('asset.read', 'DEGRADED_REPLAY', { detail: `${assetId}: ${error?.message || 'API unavailable'}` })
        return result
      }
      recordAudit('asset.read', 'FAILED', { detail: error?.message || assetId })
      const missing = error?.response?.status === 404 || error?.api?.code === 'ASSET_NOT_FOUND'
      if (!missing) assetRequestCache.delete(cacheKey)
      throw error
    }
  })()
  assetRequestCache.set(cacheKey, request)
  return request
}

export async function getBaseline(residentId = RESIDENT_ID) {
  return resolveData('residents.baseline', async () => normalizeBaseline(payload(await apiClient.get(
    `/residents/${encodeURIComponent(residentId)}/baseline`,
  ))), () => normalizeBaseline(replayData.baseline))
}

export async function getDeviceStatus() {
  return resolveData('device.status', async () => normalizeDevice(
    validateDeviceStatus(payload(await apiClient.get('/device/status'))),
  ), () => normalizeDevice(validateDeviceStatus(replayData.device)))
}

export async function getAlarmProcessingTasks({ residentId = null, limit = 20 } = {}) {
  return resolveData('alarms.processing', async () => {
    const params = { limit }
    if (residentId) params.resident_id = residentId
    const response = await apiClient.get('/alarms/processing', { params })
    return validateAlarmProcessingTasks(listFrom(payload(response)))
  }, () => [], validateAlarmProcessingTasks)
}

function stableFeedbackId(eventId, feedback) {
  const source = `${eventId}|${feedback.feedback_kind || 'CARE'}|${feedback.feedback_type || ''}|${feedback.value || ''}`
  let hash = 2166136261
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `feedback-${eventId}-${(hash >>> 0).toString(16)}`
}

export function stableInterventionResultId(eventId, residentResponse) {
  const source = `${eventId}|resident_response|${residentResponse}`
  let hash = 2166136261
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `result-${eventId}-${(hash >>> 0).toString(16)}`
}

function interventionResultPayload(event, residentResponse) {
  const timestamp = new Date().toISOString()
  return {
    schema_version: '1.0',
    result_id: stableInterventionResultId(event.event_id, residentResponse),
    event_id: event.event_id,
    started_at: timestamp,
    completed_at: timestamp,
    action_type: 'resident_response',
    tool_name: 'family_console',
    delivery_status: 'SUCCESS',
    resident_response: residentResponse,
    family_feedback: null,
    risk_after: null,
    resolved: false,
    resolution_reason: null,
    operator: 'family',
    source_mode: event.source_mode,
    simulated: event.simulated,
  }
}

export async function submitInterventionResult(event, residentResponse = 'stable') {
  const requestBody = interventionResultPayload(event, residentResponse)
  const resultId = requestBody.result_id

  if (interventionResultCache.has(resultId)) {
    recordAudit('intervention-result.write', 'IDEMPOTENT_REPLAY', { event_id: event.event_id, detail: resultId })
    return structuredClone(interventionResultCache.get(resultId))
  }

  if (runtime.mode !== 'replay') {
    try {
      const result = validateInterventionResult(payload(await apiClient.post(
        `/events/${encodeURIComponent(event.event_id)}/results`, requestBody,
        { headers: { 'Idempotency-Key': resultId, 'Content-Type': 'application/json; charset=utf-8' } },
      )))
      runtime.activeSource = 'api'
      runtime.degraded = false
      interventionResultCache.set(resultId, result)
      recordAudit('intervention-result.write', 'SUCCESS', { event_id: event.event_id, detail: resultId })
      return structuredClone(result)
    } catch (error) {
      if (!(runtime.mode === 'auto' && shouldFallback(error))) {
        recordAudit('intervention-result.write', 'FAILED', { event_id: event.event_id, detail: error?.message })
        throw error
      }
      runtime.activeSource = 'replay_dataset'
      runtime.degraded = true
      runtime.message = '干预结果接口暂不可用，确认结果仅保存在本次演示中'
      recordAudit('intervention-result.write', 'DEGRADED', { event_id: event.event_id, detail: error?.message })
    }
  }

  const result = { ...requestBody, saved_in_demo: true }
  interventionResultCache.set(resultId, result)
  recordAudit('intervention-result.write', 'REPLAY', { event_id: event.event_id, detail: resultId })
  return structuredClone(result)
}

export async function submitFamilyFeedback(eventId, feedback) {
  const feedbackKind = feedback.feedback_kind || 'CARE'
  if (!FEEDBACK_KINDS.has(feedbackKind)) throw new Error(`不支持的反馈类型：${feedbackKind}`)
  const feedbackBody = { ...feedback, feedback_kind: feedbackKind, feedback_type: 'confirm' }
  const feedbackId = feedbackBody.feedback_id || stableFeedbackId(eventId, feedbackBody)
  const requestBody = { ...feedbackBody, feedback_id: feedbackId }

  if (feedbackCache.has(feedbackId)) {
    submittedFeedbackSession.add(`${eventId}:${feedbackKind}`)
    recordAudit('feedback.write', 'IDEMPOTENT_REPLAY', { event_id: eventId, detail: feedbackId })
    return structuredClone(feedbackCache.get(feedbackId))
  }
  if (replayContext()) {
    const stored = getRecordedFeedback(eventId).find((record) => record.feedback_id === feedbackId)
    if (stored) {
      submittedFeedbackSession.add(`${eventId}:${feedbackKind}`)
      feedbackCache.set(feedbackId, stored)
      recordAudit('feedback.write', 'IDEMPOTENT_REPLAY', { event_id: eventId, detail: feedbackId })
      return structuredClone(stored)
    }
  }

  if (runtime.mode !== 'replay') {
    try {
      const response = await apiClient.post(`/events/${eventId}/feedback`, requestBody, {
        headers: { 'Idempotency-Key': feedbackId, 'Content-Type': 'application/json; charset=utf-8' },
      })
      runtime.activeSource = 'api'
      runtime.degraded = false
      const result = payload(response)
      feedbackCache.set(feedbackId, result)
      submittedFeedbackSession.add(`${eventId}:${feedbackKind}`)
      recordAudit('feedback.write', 'SUCCESS', { event_id: eventId, detail: feedbackId })
      return normalizeFeedbackRecord({ ...result, feedback_id: result?.feedback_id || feedbackId, event_id: eventId }, {
        feedback_kind: feedbackKind, source_mode: 'LIVE_DEVICE', simulated: false, saved_in_demo: false,
      })
    } catch (error) {
      if (!(runtime.mode === 'auto' && shouldFallback(error))) {
        recordAudit('feedback.write', 'FAILED', { event_id: eventId, detail: error?.message })
        throw error
      }
      runtime.activeSource = 'replay_dataset'
      runtime.degraded = true
      runtime.message = '反馈接口暂不可用，结果仅保存在本次演示中'
      recordAudit('feedback.write', 'DEGRADED', { event_id: eventId, detail: error?.message })
    }
  }

  const result = saveReplayFeedback(normalizeFeedbackRecord({
    event_id: eventId, ...requestBody, recorded_at: new Date().toISOString(), saved_in_demo: true,
  }))
  feedbackCache.set(feedbackId, result)
  submittedFeedbackSession.add(`${eventId}:${feedbackKind}`)
  recordAudit('feedback.write', 'REPLAY', { event_id: eventId, detail: feedbackId })
  return structuredClone(result)
}

export { API_BASE_URL, PAGES_BUILD, RESIDENT_ID, shouldFallback, stableFeedbackId }
