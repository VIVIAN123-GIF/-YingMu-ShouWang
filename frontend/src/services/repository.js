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
import deviceSnapshotReplay from '../replay-data/device-snapshot.json'
import sceneCalibrationReplay from '../replay-data/scene-calibration.json'
import { DATA_MODES } from '../domain/constants'
import {
  validateAgentExplanationJob, validateAlarmProcessingTasks, validateAsset, validateDashboard, validateDeviceControlResult, validateDeviceSnapshot, validateDeviceStatus, validateEventList, validateEventViewModel, validateForewarningHistory, validateForewarningSnapshot, validateInterventionResult, validateRiskReviews, validateSceneCalibration,
} from '../domain/validation'
import {
  normalizeBaseline, normalizeDashboard, normalizeDevice, normalizeEvent, normalizeWeeklyReport,
} from './viewModel'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const RESIDENT_ID = import.meta.env.VITE_RESIDENT_ID || 'resident-001'
const PAGES_BUILD = import.meta.env.VITE_PAGES_BUILD === 'true'
const AUTHORIZED_CLIP_URL = import.meta.env.VITE_AUTHORIZED_CLIP_URL?.trim() || ''
// The normal workspace combines API records with the authorized replay index.
// Explicit api/replay modes remain available for isolated verification builds.
const configuredMode = import.meta.env.VITE_DATA_MODE || 'auto'
const initialMode = PAGES_BUILD ? 'replay' : configuredMode

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  // Device status may require a round trip to the live provider; keep the
  // dashboard from failing while the other API calls are still healthy.
  timeout: 8000,
  headers: { Accept: 'application/json', 'Content-Type': 'application/json; charset=utf-8' },
})

export function normalizeApiError(error) {
  const body = error?.response?.data
  const detail = body?.error || body?.detail
  if (!detail && error?.message === 'Network Error') error.message = '网络连接失败'
  if (!detail && error?.code === 'ECONNABORTED') error.message = '请求超时'
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
  deviceSnapshot: structuredClone(deviceSnapshotReplay),
  sceneCalibration: structuredClone(sceneCalibrationReplay),
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
const eventSessionCache = new Map()
const resourceHealth = new Map()
let lastDeviceStatus = null
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
  return runtime.mode === 'auto' || runtime.mode === 'replay' || runtime.activeSource === 'replay_dataset'
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
  message: initialMode === 'replay' ? '当前使用授权回放' : '',
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
  runtime.message = mode === 'replay' ? '当前使用授权回放' : ''
  sessionStorage.setItem('yingmu-data-mode', mode)
  recordAudit('data-mode.change', 'SUCCESS', { detail: `mode=${mode}` })
}

function eventTimestamp(event) {
  const timestamp = Date.parse(event?.created_at || '')
  return Number.isNaN(timestamp) ? 0 : timestamp
}

function compareEventsNewestFirst(left, right) {
  const timeDifference = eventTimestamp(right) - eventTimestamp(left)
  if (timeDifference !== 0) return timeDifference
  return String(right?.event_id || '').localeCompare(String(left?.event_id || ''))
}

export function mergeEventCollections(primaryEvents = [], secondaryEvents = []) {
  const byId = new Map()
  secondaryEvents.forEach((event) => byId.set(event.event_id, event))
  primaryEvents.forEach((event) => byId.set(event.event_id, event))
  return [...byId.values()].sort(compareEventsNewestFirst)
}

function replayEventById(eventId) {
  return replayData.events.find((event) => event.event_id === eventId) || null
}

function eventNotFound(eventId) {
  const error = new Error(`事件不存在（${eventId}）`)
  error.api = { code: 'EVENT_NOT_FOUND', message: error.message, request_id: null }
  error.response = { status: 404 }
  return error
}

function payload(response) {
  return response?.data?.data ?? response?.data
}

function shouldFallback(error) {
  if (error?.name === 'DataContractError') return false
  const status = error?.response?.status
  return !error?.response || status === 404 || status === 501 || status >= 500
}

async function resolveData(operation, apiRequest, replayFactory, validate = (value) => value, canFallback = shouldFallback) {
  if (runtime.mode === 'replay') {
    runtime.activeSource = 'replay_dataset'
    runtime.degraded = false
    const result = validate(structuredClone(replayFactory()))
    resourceHealth.set(operation, false)
    recordAudit(operation, 'REPLAY', { detail: 'authorized-replay-dataset', event_id: result?.event_id, ruleset_version: result?.ruleset_version })
    return result
  }

  try {
    const result = validate(await apiRequest())
    runtime.activeSource = 'api'
    runtime.degraded = false
    runtime.message = ''
    runtime.lastError = null
    resourceHealth.set(operation, false)
    recordAudit(operation, 'SUCCESS', { detail: 'fastapi', event_id: result?.event_id, ruleset_version: result?.ruleset_version })
    return result
  } catch (error) {
    runtime.lastError = error?.message || '后端接口请求失败'
    resourceHealth.set(operation, true)
    if (runtime.mode === 'auto' && canFallback(error)) {
      runtime.activeSource = 'replay_dataset'
      runtime.degraded = true
      runtime.message = '服务暂时不可用，已切换至授权回放'
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
  const [events, device, baseline] = await Promise.all([
    getEvents(residentId),
    getDeviceStatus(),
    getBaseline(residentId),
  ])
  const replayFeedback = getRecordedFeedback().filter((record) => record.feedback_kind === 'CARE').at(-1)?.value
  const dashboardBaseline = {
    ...baseline,
    today: {
      ...(baseline.today || replayData.dashboard.today),
      care_status: replayFeedback || baseline.today?.care_status || replayData.dashboard.today?.care_status || null,
    },
    risk_trend: baseline.risk_trend || replayData.dashboard.risk_trend,
    pre_fall_summary: baseline.pre_fall_summary || replayData.dashboard.pre_fall_summary,
  }
  const result = validateDashboard(normalizeDashboard({ events, device, baseline: dashboardBaseline, residentId }))
  if (runtime.mode === 'auto') {
    const partial = ['events.list', 'device.status', 'residents.baseline'].some((operation) => resourceHealth.get(operation))
    runtime.activeSource = 'combined'
    runtime.degraded = partial
    runtime.message = partial
      ? '部分实时服务暂不可用，已保留可用数据并补充授权回放'
      : '实时记录与授权回放已汇入同一视图'
  }
  recordAudit('dashboard.read', runtime.degraded ? 'PARTIAL' : 'SUCCESS', { detail: runtime.activeSource })
  return result
}

export async function getEvents(residentId = RESIDENT_ID) {
  const readApiEvents = async () => {
    const response = await apiClient.get('/events', { params: { resident_id: residentId } })
    return validateEventList(listFrom(payload(response))).map(normalizeEvent)
  }
  const readReplayEvents = () => validateEventList(structuredClone(replayData.events)).map(normalizeEvent)

  if (runtime.mode === 'replay') {
    const result = readReplayEvents().sort(compareEventsNewestFirst)
    eventSessionCache.set(residentId, result)
    runtime.activeSource = 'replay_dataset'
    runtime.degraded = false
    resourceHealth.set('events.list', false)
    recordAudit('events.list', 'REPLAY', { detail: 'authorized-replay-dataset' })
    return structuredClone(result)
  }

  if (runtime.mode === 'api') {
    const result = (await readApiEvents()).sort(compareEventsNewestFirst)
    eventSessionCache.set(residentId, result)
    runtime.activeSource = 'api'
    runtime.degraded = false
    runtime.message = ''
    runtime.lastError = null
    resourceHealth.set('events.list', false)
    recordAudit('events.list', 'SUCCESS', { detail: 'fastapi' })
    return structuredClone(result)
  }

  try {
    const apiEvents = await readApiEvents()
    const result = mergeEventCollections(apiEvents, readReplayEvents())
    eventSessionCache.set(residentId, result)
    runtime.activeSource = 'combined'
    runtime.degraded = false
    runtime.message = '实时记录与授权回放已汇入同一时间轴'
    runtime.lastError = null
    resourceHealth.set('events.list', false)
    recordAudit('events.list', 'MERGED', { detail: `api=${apiEvents.length}; replay=${replayData.events.length}; merged=${result.length}` })
    return structuredClone(result)
  } catch (error) {
    runtime.lastError = error?.message || '后端接口请求失败'
    resourceHealth.set('events.list', true)
    if (!shouldFallback(error)) {
      recordAudit('events.list', 'FAILED', { detail: error?.message || 'contract/api error' })
      throw error
    }
    const result = mergeEventCollections(eventSessionCache.get(residentId) || [], readReplayEvents())
    eventSessionCache.set(residentId, result)
    runtime.activeSource = 'replay_dataset'
    runtime.degraded = true
    runtime.message = '实时连接暂不可用，已保留现有记录并继续显示授权回放'
    recordAudit('events.list', 'DEGRADED_REPLAY', { detail: error?.message || 'FastAPI unavailable' })
    return structuredClone(result)
  }
}

export async function getRiskReviews(residentId = RESIDENT_ID, limit = 20) {
  return resolveData('risk-reviews.list', async () => {
    const response = await apiClient.get('/risk/reviews', { params: { resident_id: residentId, limit } })
    return validateRiskReviews(listFrom(payload(response)))
  }, () => [], validateRiskReviews)
}

export async function getEvent(eventId) {
  const encodedEventId = encodeURIComponent(eventId)
  return resolveData('event.detail', async () => {
    const [eventResponse, snapshotResponse] = await Promise.all([
      apiClient.get(`/events/${encodedEventId}`),
      apiClient.get(`/events/${encodedEventId}/forewarning`),
    ])
    const event = payload(eventResponse)
    validateEventViewModel(event)
    const snapshots = listFrom(payload(snapshotResponse)).map((snapshot, index) => validateForewarningSnapshot(snapshot, `forewarning[${index}]`))
    return normalizeEvent({ ...event, forewarning_snapshots: snapshots, feedback_records: getRecordedFeedback(event.event_id) })
  }, () => {
    const replayEvent = replayEventById(eventId)
    if (!replayEvent) throw eventNotFound(eventId)
    return normalizeEvent({
      ...hydrateReplayEvent(replayEvent),
      feedback_records: getRecordedFeedback(eventId),
      forewarning_snapshots: replayForewarningFor(eventId),
    })
  }, validateEventViewModel)
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
  return validateAgentExplanationJob({ event_id: eventId, status: 'FALLBACK', request_id: `replay-${eventId}`, event_version_hash: 'replay-explanation-v1', generated_by: 'replay-explanation-v1', fallback_used: true, attempt_count: 1, error_code: null, created_at: createdAt, completed_at: replayTimePlusSeconds(createdAtSource, 5), explanation: { schema_version: 'agent-explanation/1.0', request_id: `replay-${eventId}`, event_id: eventId, ...template, capability_notice: '授权回放', generated_by: 'replay-explanation-v1', fallback_used: true } })
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
        summary: '基于固定依据的脱敏解释',
        reasoning_points: ['系统已汇总相关证据。'],
        recommended_action_text: '按演示事件中的分级干预流程继续查看。',
        capability_notice: '已加载授权媒体内容。',
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
      notice: `素材内容暂不可用（${assetId}）`,
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
  const result = await resolveData('device.status', async () => normalizeDevice(
    validateDeviceStatus(payload(await apiClient.get('/device/status'))),
  ), () => normalizeDevice(validateDeviceStatus(replayData.device)))
  lastDeviceStatus = result
  return result
}

export async function getDeviceSnapshot() {
  return resolveData('device.snapshot', async () => validateDeviceSnapshot(
    payload(await apiClient.get('/device/snapshot')),
  ), () => validateDeviceSnapshot(replayData.deviceSnapshot), validateDeviceSnapshot)
}

export async function createDeviceSnapshot() {
  return resolveData('device.snapshot.capture', async () => {
    // A live capture includes provider capture plus private-media download;
    // keep the normal dashboard timeout for all other API calls.
    const response = await apiClient.post('/device/snapshot', null, { timeout: 90000 })
    return response.data?.asset || response.data
  }, () => null)
}

export async function getPrivateAssetBlob(assetId) {
  if (!assetId) throw new Error('asset_id is required')
  const response = await fetch(`/media/assets/${encodeURIComponent(assetId)}`, {
    credentials: 'include',
    headers: { Accept: 'image/jpeg,image/png,image/webp' },
  })
  if (!response.ok) {
    let detail = null
    try { detail = await response.json() } catch { /* Response may not be JSON. */ }
    const error = new Error(detail?.error?.message || `媒体加载失败（${response.status}）`)
    error.api = { code: detail?.error?.code || 'MEDIA_REQUEST_FAILED', message: error.message, request_id: detail?.error?.request_id || null }
    error.response = { status: response.status }
    throw error
  }
  return response.blob()
}

/* 摄像头直播功能暂时停用。
export async function getDeviceLiveAddress() {
  return resolveData('device.live-address', async () => payload(await apiClient.get('/device/live-address')), () => {
    throw Object.assign(new Error('直播仅在实时设备模式下可用'), { response: { status: 503 } })
  })
}
*/

function controlError(code, message) {
  const error = new Error(message)
  error.api = { code, message, request_id: null }
  return error
}

export async function stopDeviceCollection(controlToken) {
  if (!controlToken || typeof controlToken !== 'string') {
    throw controlError('CONTROL_TOKEN_REQUIRED', '请输入现场控制令牌')
  }
  if (runtime.mode === 'replay' || !lastDeviceStatus || lastDeviceStatus.source_mode !== 'LIVE_DEVICE' || lastDeviceStatus.simulated) {
    const error = controlError('LIVE_CONTROL_UNAVAILABLE', '只有已确认的实时设备可以执行停止采集')
    recordAudit('device.stop', 'BLOCKED', { detail: error.api.code })
    throw error
  }
  try {
    const result = validateDeviceControlResult(payload(await apiClient.post('/device/stop', null, {
      headers: { 'X-Control-Token': controlToken },
    })))
    runtime.activeSource = 'api'
    runtime.degraded = false
    runtime.message = ''
    runtime.lastError = null
    lastDeviceStatus = { ...lastDeviceStatus, ...result, online: result.online ?? lastDeviceStatus.online }
    recordAudit('device.stop', 'SUCCESS', { detail: 'collection-stopped' })
    return result
  } catch (error) {
    runtime.lastError = error?.message || '停止采集失败'
    recordAudit('device.stop', 'FAILED', { detail: error?.api?.code || 'CONTROL_REQUEST_FAILED' })
    throw error
  }
}

function replaySceneCalibration(sceneConfigId) {
  if (replayData.sceneCalibration.scene_config_id !== sceneConfigId) {
    throw controlError('SCENE_CONFIG_MISSING', '场景标定不存在')
  }
  return replayData.sceneCalibration
}

function sceneFallbackAllowed(error) {
  if (['SCENE_CONFIG_MISSING', 'SCENE_CONFIG_INVALID'].includes(error?.api?.code)) return false
  return shouldFallback(error)
}

export async function getSceneCalibration(sceneConfigId) {
  if (!sceneConfigId || typeof sceneConfigId !== 'string') {
    throw controlError('SCENE_CONFIG_REQUIRED', '缺少场景配置标识')
  }
  return resolveData('scene-calibration.read', async () => validateSceneCalibration(payload(await apiClient.get(
    `/scene-calibrations/${encodeURIComponent(sceneConfigId)}`,
  ))), () => validateSceneCalibration(replaySceneCalibration(sceneConfigId)), validateSceneCalibration, sceneFallbackAllowed)
}

export async function getCurrentSceneCalibration() {
  return resolveData('scene-calibration.current', async () => validateSceneCalibration(payload(await apiClient.get(
    '/scene-calibrations/current',
  ))), () => validateSceneCalibration(replayData.sceneCalibration), validateSceneCalibration, shouldFallback)
}

function replayForewarningHistory(residentId, { from = null, to = null, limit = 100 } = {}) {
  const fromTimestamp = from ? Date.parse(from) : Number.NEGATIVE_INFINITY
  const toTimestamp = to ? Date.parse(to) : Number.POSITIVE_INFINITY
  return replayData.forewarning
    .map((snapshot) => ({ ...snapshot, resident_id: residentId }))
    .filter((snapshot) => {
      const timestamp = Date.parse(snapshot.evaluated_at)
      return timestamp >= fromTimestamp && timestamp <= toTimestamp
    })
    .sort((left, right) => Date.parse(right.evaluated_at) - Date.parse(left.evaluated_at))
    .slice(0, limit)
}

export async function getLatestForewarning(residentId = RESIDENT_ID) {
  return resolveData('resident.forewarning.latest', async () => {
    const result = payload(await apiClient.get(`/residents/${encodeURIComponent(residentId)}/forewarning/latest`))
    return result === null ? null : validateForewarningSnapshot(result, 'resident_forewarning.latest')
  }, () => replayForewarningHistory(residentId, { limit: 1 })[0] || null, (result) => (
    result === null ? null : validateForewarningSnapshot(result, 'resident_forewarning.latest')
  ))
}

export async function getForewarningHistory(residentId = RESIDENT_ID, { from = null, to = null, limit = 500 } = {}) {
  const safeLimit = Math.min(500, Math.max(1, Number.isInteger(limit) ? limit : 500))
  const params = { limit: safeLimit }
  if (from) params.from = from
  if (to) params.to = to
  return resolveData('resident.forewarning.history', async () => validateForewarningHistory(listFrom(payload(await apiClient.get(
    `/residents/${encodeURIComponent(residentId)}/forewarning`, { params },
  )))), () => replayForewarningHistory(residentId, { from, to, limit: safeLimit }), validateForewarningHistory)
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
      runtime.message = '服务暂时不可用，请稍后重试'
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
      const response = await apiClient.post(`/events/${encodeURIComponent(eventId)}/feedback`, requestBody, {
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
      runtime.message = '服务暂时不可用，请稍后重试'
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
