import axios from 'axios'
import { reactive } from 'vue'
import dashboardMock from '../mocks/dashboard.json'
import eventsMock from '../mocks/events.json'
import weeklyMock from '../mocks/weekly.json'
import deviceMock from '../mocks/device.json'
import assetsMock from '../mocks/assets.json'
import observationsMock from '../mocks/observations.json'
import baselineMock from '../mocks/baseline.json'
import { DATA_MODES } from '../domain/constants'
import { validateDashboard, validateEventList, validateEventViewModel } from '../domain/validation'
import {
  normalizeBaseline, normalizeDashboard, normalizeDevice, normalizeEvent, normalizeWeeklyReport,
} from './viewModel'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const AUTHORIZED_CLIP_URL = import.meta.env.VITE_AUTHORIZED_CLIP_URL || ''
const RESIDENT_ID = import.meta.env.VITE_RESIDENT_ID || 'resident-001'
const configuredMode = import.meta.env.VITE_DATA_MODE || 'auto'
const initialMode = sessionStorage.getItem('yingmu-data-mode') || configuredMode

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 2800,
  headers: { Accept: 'application/json' },
})

const mocks = {
  dashboard: structuredClone(dashboardMock),
  events: structuredClone(eventsMock),
  weekly: structuredClone(weeklyMock),
  device: structuredClone(deviceMock),
  assets: structuredClone(assetsMock),
  observations: structuredClone(observationsMock),
  baseline: structuredClone(baselineMock),
}

const feedbackCache = new Map()

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

function withAuthorizedClip(asset) {
  if (!AUTHORIZED_CLIP_URL || asset.asset_id !== 'asset-fall-authorized') return asset
  return {
    ...asset,
    fallback_url: AUTHORIZED_CLIP_URL,
    available: true,
    verification_status: 'PROVIDED_UNVERIFIED',
    notice: '已配置授权片段，页面将在成功加载后标记为可播放。',
  }
}

export async function getDashboard(residentId = RESIDENT_ID) {
  return resolveData('dashboard.read', async () => {
    const [eventsResponse, deviceResponse, baselineResponse] = await Promise.all([
      client.get('/api/v1/events', { params: { resident_id: residentId } }),
      client.get('/api/v1/device/status'),
      client.get(`/api/v1/residents/${residentId}/baseline`),
    ])
    const events = validateEventList(listFrom(payload(eventsResponse)))
    const baseline = payload(baselineResponse)
    return normalizeDashboard({ events, device: payload(deviceResponse), baseline, residentId })
  }, () => mocks.dashboard, validateDashboard)
}

export async function getEvents(residentId = RESIDENT_ID) {
  return resolveData('events.list', async () => {
    const response = await client.get('/api/v1/events', { params: { resident_id: residentId } })
    return validateEventList(listFrom(payload(response))).map(normalizeEvent)
  }, () => mocks.events.map(normalizeEvent), validateEventList)
}

export async function getEvent(eventId) {
  return resolveData('event.detail', async () => {
    const event = payload(await client.get(`/api/v1/events/${eventId}`))
    validateEventViewModel(event)
    return normalizeEvent(event)
  }, () => normalizeEvent(hydrateMockEvent(mocks.events.find((event) => event.event_id === eventId) || mocks.events[0])), validateEventViewModel)
}

export async function getWeeklyReport(residentId = RESIDENT_ID) {
  return resolveData('weekly.read', async () => normalizeWeeklyReport(
    payload(await client.get('/api/v1/reports/weekly', { params: { resident_id: residentId } })),
  ), () => normalizeWeeklyReport(mocks.weekly))
}

export async function getBaseline(residentId = RESIDENT_ID) {
  return resolveData('baseline.read', async () => normalizeBaseline(
    payload(await client.get(`/api/v1/residents/${residentId}/baseline`)),
  ), () => normalizeBaseline(mocks.baseline))
}

export async function getDeviceStatus() {
  return resolveData('device.status', async () => normalizeDevice(
    payload(await client.get('/api/v1/device/status')),
  ), () => normalizeDevice(mocks.device))
}

export async function getSnapshot() {
  return resolveData('device.snapshot', async () => payload(await client.get('/api/v1/device/snapshot')), () => withAuthorizedClip(mocks.assets[0]))
}

export async function getAsset(assetId) {
  return resolveData('asset.read', async () => payload(await client.get(`/api/v1/assets/${assetId}`)), () => withAuthorizedClip(
    mocks.assets.find((asset) => asset.asset_id === assetId) || mocks.assets[0],
  ))
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

export async function submitFamilyFeedback(eventId, feedback) {
  const feedbackId = feedback.feedback_id || stableFeedbackId(eventId, feedback)
  const requestBody = { ...feedback, feedback_id: feedbackId }

  if (feedbackCache.has(feedbackId)) {
    recordAudit('feedback.write', 'IDEMPOTENT_REPLAY', { event_id: eventId, detail: feedbackId })
    return structuredClone(feedbackCache.get(feedbackId))
  }

  if (runtime.mode !== 'mock') {
    try {
      const response = await client.post(`/api/v1/events/${eventId}/feedback`, requestBody, {
        headers: { 'Idempotency-Key': feedbackId },
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

export { RESIDENT_ID, shouldFallback, stableFeedbackId }
