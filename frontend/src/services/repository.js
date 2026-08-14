import axios from 'axios'
import { reactive } from 'vue'
import dashboardMock from '../mocks/dashboard.json'
import eventsMock from '../mocks/events.json'
import weeklyMock from '../mocks/weekly.json'
import deviceMock from '../mocks/device.json'
import observationsMock from '../mocks/observations.json'
import baselineMock from '../mocks/baseline.json'
import { DATA_MODES } from '../domain/constants'
import {
  validateAlarmProcessingTasks, validateDashboard, validateDeviceStatus, validateEventList, validateEventViewModel, validateInterventionResult,
} from '../domain/validation'
import {
  normalizeBaseline, normalizeDashboard, normalizeDevice, normalizeEvent, normalizeWeeklyReport,
} from './viewModel'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const RESIDENT_ID = import.meta.env.VITE_RESIDENT_ID || 'resident-001'
const configuredMode = import.meta.env.VITE_DATA_MODE || 'auto'
const initialMode = sessionStorage.getItem('yingmu-data-mode') || configuredMode

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 2800,
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

const mocks = {
  dashboard: structuredClone(dashboardMock),
  events: structuredClone(eventsMock),
  weekly: structuredClone(weeklyMock),
  device: structuredClone(deviceMock),
  observations: structuredClone(observationsMock),
  baseline: structuredClone(baselineMock),
}

const feedbackCache = new Map()
const interventionResultCache = new Map()

export const runtime = reactive({
  mode: DATA_MODES[initialMode] ? initialMode : 'auto',
  activeSource: initialMode === 'mock' ? 'mock' : 'api',
  degraded: false,
  message: initialMode === 'mock' ? '当前使用固定 JSON 演示数据' : '',
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
  if (!DATA_MODES[mode]) return
  runtime.mode = mode
  runtime.activeSource = mode === 'mock' ? 'mock' : 'api'
  runtime.degraded = false
  runtime.lastError = null
  runtime.message = mode === 'mock' ? '当前使用固定 JSON 演示数据' : ''
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

async function resolveData(operation, apiRequest, mockFactory, validate = (value) => value) {
  if (runtime.mode === 'mock') {
    runtime.activeSource = 'mock'
    runtime.degraded = false
    const result = validate(structuredClone(mockFactory()))
    recordAudit(operation, 'MOCK', { detail: 'fixed-json', event_id: result?.event_id, ruleset_version: result?.ruleset_version })
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
      runtime.activeSource = 'mock'
      runtime.degraded = true
      runtime.message = 'FastAPI 暂不可用，已自动切换固定 JSON 演示数据'
      const result = validate(structuredClone(mockFactory()))
      recordAudit(operation, 'DEGRADED', { detail: error?.message || 'FastAPI unavailable', event_id: result?.event_id, ruleset_version: result?.ruleset_version })
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
  return mocks.observations.filter((observation) => ids.has(observation.observation_id))
}

function hydrateMockEvent(event) {
  return { ...event, observations: observationsFor(event) }
}

export async function getDashboard(residentId = RESIDENT_ID) {
  return resolveData('dashboard.read', async () => {
    const [eventsResponse, deviceResponse] = await Promise.all([
      apiClient.get('/events', { params: { resident_id: residentId } }),
      apiClient.get('/device/status'),
    ])
    const events = validateEventList(listFrom(payload(eventsResponse)))
    const baseline = mocks.baseline
    return normalizeDashboard({ events, device: validateDeviceStatus(payload(deviceResponse)), baseline, residentId })
  }, () => normalizeDashboard({
    events: mocks.events, device: validateDeviceStatus(mocks.device), baseline: mocks.baseline, residentId,
  }), validateDashboard)
}

export async function getEvents(residentId = RESIDENT_ID) {
  return resolveData('events.list', async () => {
    const response = await apiClient.get('/events', { params: { resident_id: residentId } })
    return validateEventList(listFrom(payload(response))).map(normalizeEvent)
  }, () => mocks.events.map(normalizeEvent), validateEventList)
}

export async function getEvent(eventId) {
  return resolveData('event.detail', async () => {
    const event = payload(await apiClient.get(`/events/${eventId}`))
    validateEventViewModel(event)
    return normalizeEvent(event)
  }, () => normalizeEvent(hydrateMockEvent(mocks.events.find((event) => event.event_id === eventId) || mocks.events[0])), validateEventViewModel)
}

export async function getWeeklyReport(residentId = RESIDENT_ID) {
  return normalizeWeeklyReport(structuredClone(mocks.weekly))
}

export async function getBaseline(residentId = RESIDENT_ID) {
  return normalizeBaseline(structuredClone(mocks.baseline))
}

export async function getDeviceStatus() {
  return resolveData('device.status', async () => normalizeDevice(
    validateDeviceStatus(payload(await apiClient.get('/device/status'))),
  ), () => normalizeDevice(validateDeviceStatus(mocks.device)))
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
  const source = `${eventId}|${feedback.feedback_type || ''}|${feedback.value || ''}`
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

  if (runtime.mode !== 'mock') {
    try {
      const result = validateInterventionResult(payload(await apiClient.post(
        `/events/${event.event_id}/intervene`, null,
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
      runtime.activeSource = 'mock'
      runtime.degraded = true
      runtime.message = '干预结果接口暂不可用，确认结果仅保存在本次演示中'
      recordAudit('intervention-result.write', 'DEGRADED', { event_id: event.event_id, detail: error?.message })
    }
  }

  const result = { ...requestBody, saved_in_demo: true }
  interventionResultCache.set(resultId, result)
  recordAudit('intervention-result.write', 'MOCK', { event_id: event.event_id, detail: resultId })
  return structuredClone(result)
}

export async function submitFamilyFeedback(eventId, feedback) {
  const feedbackBody = { ...feedback, feedback_type: 'confirm' }
  const feedbackId = feedbackBody.feedback_id || stableFeedbackId(eventId, feedbackBody)
  const requestBody = { ...feedbackBody, feedback_id: feedbackId }

  if (feedbackCache.has(feedbackId)) {
    recordAudit('feedback.write', 'IDEMPOTENT_REPLAY', { event_id: eventId, detail: feedbackId })
    return structuredClone(feedbackCache.get(feedbackId))
  }

  if (runtime.mode !== 'mock') {
    try {
      const response = await apiClient.post(`/events/${eventId}/feedback`, requestBody, {
        headers: { 'Idempotency-Key': feedbackId, 'Content-Type': 'application/json; charset=utf-8' },
      })
      runtime.activeSource = 'api'
      runtime.degraded = false
      const result = payload(response)
      feedbackCache.set(feedbackId, result)
      recordAudit('feedback.write', 'SUCCESS', { event_id: eventId, detail: feedbackId })
      return result
    } catch (error) {
      if (!(runtime.mode === 'auto' && shouldFallback(error))) {
        recordAudit('feedback.write', 'FAILED', { event_id: eventId, detail: error?.message })
        throw error
      }
      runtime.activeSource = 'mock'
      runtime.degraded = true
      runtime.message = '反馈接口暂不可用，结果仅保存在本次演示中'
      recordAudit('feedback.write', 'DEGRADED', { event_id: eventId, detail: error?.message })
    }
  }

  const result = { event_id: eventId, ...requestBody, saved_in_demo: true, updated_at: new Date().toISOString() }
  feedbackCache.set(feedbackId, result)
  recordAudit('feedback.write', 'MOCK', { event_id: eventId, detail: feedbackId })
  return structuredClone(result)
}

export { API_BASE_URL, RESIDENT_ID, shouldFallback, stableFeedbackId }
