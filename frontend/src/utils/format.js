import { EVENT_STATUSES, RISK_DOMAINS } from '../domain/constants'

export function formatDateTime(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date(value))
}

export function formatPercent(value) {
  if (value === null || value === undefined) return '—'
  return `${Math.round(Number(value) * 100)}%`
}

export function formatRiskScore(value) {
  if (value === null || value === undefined) return '—'
  return Math.round(Number(value) * 100)
}

export function domainLabel(value) {
  return RISK_DOMAINS[value] || value || '未知方向'
}

export function statusLabel(value) {
  return EVENT_STATUSES[value] || value || '未知状态'
}
