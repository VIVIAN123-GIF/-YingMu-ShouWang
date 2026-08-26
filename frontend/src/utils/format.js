import { EVENT_STATUSES, RISK_DOMAINS } from '../domain/constants'

const EVIDENCE_TYPE_LABELS = Object.freeze({
  sit_to_stand_transition: '有效坐站转换',
  rapid_rise: '起身偏快',
  slow_rise: '起身偏慢',
  trunk_sway: '起身后躯干摆动',
  post_rise_lateral_drift: '起身后横向漂移',
  support_base_change: '支撑面变化',
  compensatory_step: '补偿步',
  gait_instability: '步态不对称',
  assessment_indeterminate: '本次评估不可判定',
  posture_recovered: '姿态已恢复',
})

export function formatDateTime(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    timeZone: 'Asia/Shanghai',
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

export function formatAssetId(value) {
  return value || '暂无可追溯视频'
}

export function domainLabel(value) {
  return RISK_DOMAINS[value] || value || '未知方向'
}

export function statusLabel(value) {
  return EVENT_STATUSES[value] || value || '未知状态'
}

export function evidenceTypeLabel(value) {
  return EVIDENCE_TYPE_LABELS[value] || value || '未知证据'
}
