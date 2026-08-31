import { EVENT_STATUSES, RISK_DOMAINS, RISK_LEVELS, SOURCE_MODES } from '../domain/constants'

const EVIDENCE_TYPE_LABELS = Object.freeze({
  sit_to_stand_transition: '老人完成坐下和站起动作',
  rapid_rise: '起身偏快',
  slow_rise: '起身偏慢',
  trunk_sway: '起身后躯干摆动',
  post_rise_lateral_drift: '起身后横向漂移',
  support_base_change: '支撑面变化',
  compensatory_step: '补偿步',
  gait_instability: '行走状态不稳',
  assessment_indeterminate: '本次评估不可判定',
  posture_recovered: '姿态已恢复',
  low_illumination: '照明不足',
  activity_range_decline: '活动范围下降',
  day_night_rhythm_change: '昼夜作息变化',
  unauthorized_visitor: '未授权访客',
  unusual_dwell_time: '停留时间异常',
  fraud_keyword: '高风险话术关键词',
  stream_unavailable: '实时画面不可用',
  sit_to_stand_transition_confirmed: '坐站转换已确认',
  post_rise_pelvis_lateral_excursion_norm: '起身后骨盆横向偏移',
  sit_to_stand_duration: '坐站转换时长',
  trunk_sway_ratio: '躯干摇晃比例',
  illumination: '环境照度',
  stable_posture_duration: '稳定姿态持续时间',
  stable_trunk_angle_deg: '稳定躯干角度',
  daily_activity_index: '每日活动指数',
  sleep_time_offset: '作息时间偏移',
  authorized_visitor_match: '授权访客匹配结果',
  visitor_dwell_time: '访客停留时间',
  risk_phrase_count: '高风险话术数量',
  stream_available: '实时画面可用状态',
})

const TIME_SCALE_LABELS = Object.freeze({ SHORT: '短期', MEDIUM: '中期', LONG: '长期' })
const UNIT_LABELS = Object.freeze({
  boolean: '是否',
  body_scale: '身体尺度',
  second: '秒',
  ratio: '比例',
  lux: '勒克斯',
  degree: '度',
  index: '指数',
  minute: '分钟',
  count: '次',
})

const LOCATION_LABELS = Object.freeze({
  living_room: '客厅',
  bedroom: '卧室',
  kitchen: '厨房',
  bathroom: '卫生间',
  hallway: '走廊',
})

const ZONE_IDENTIFIER_LABELS = Object.freeze({
  'fixed-chair-support': '固定座椅支撑区',
  'visible-floor-safe': '可见地面安全区',
})

const MEDIA_TITLE_LABELS = Object.freeze({
  'Authorized simulated living-room replay': '授权模拟客厅回放',
})

const VALUE_LABELS = Object.freeze({
  VALID: '完整评估',
  PARTIAL: '降级评估',
  INSUFFICIENT: '数据不足',
  PROVISIONAL: '初步结果',
  STABLE: '稳定',
  UNKNOWN: '未知',
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
  PERIODIC: '周期评估',
  PRE_INTERVENTION: '干预前',
  POST_INTERVENTION: '干预后',
  PENDING: '等待处理',
  PROCESSING: '处理中',
  RETRY: '正在重试',
  RETRYING: '正在重试',
  SUCCESS: '成功',
  FAILED: '失败',
  FALLBACK: '降级处理',
  SUBMITTED: '已提交',
  RECORDED: '已记录',
  FAMILY_FEEDBACK: '家属反馈',
  INTERVENTION: '干预',
  RULE: '规则评估',
  RISING: '上升',
  FALLING: '下降',
  voice: '语音提醒',
  gait_adapter: '步态适配器',
  pose: '姿态分析',
  environment: '环境分析',
  tracking: '活动追踪',
  audio: '音频分析',
  offline_replay_intervention: '离线回放干预',
  offline_replay_voice: '离线回放语音提醒',
  ezviz_voice: '萤石语音提醒',
  family_console: '家属控制台',
  'authorized-replay-c6c': '授权回放设备',
  EZVIZ_CLOUD: '萤石云连接',
  AUTHORIZED: '已授权',
  UNAUTHORIZED: '未授权',
  AUTHORIZED_LOCAL_CLIP: '已授权本地片段',
  VERIFIED_LIVE_CAPTURE: '已验证实时抓拍',
  SERVER_MANAGED_SNAPSHOT: '服务端管理抓拍',
  system: '系统',
  family: '家属',
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

export function mediaTitleLabel(value) {
  const title = String(value || '').trim()
  const unavailableMatch = /^Simulated unavailable media \(([^)]+)\)$/i.exec(title)
  if (unavailableMatch) return `模拟不可用媒体（${unavailableMatch[1]}）`
  return MEDIA_TITLE_LABELS[title] || title || '事件画面'
}

export function mediaNoticeLabel(value) {
  const notice = String(value || '').trim()
  if (notice === 'Simulated metadata only; no private media is stored.') return '仅模拟元数据，无实际媒体录像存储'
  return notice
}

export function domainLabel(value) {
  return RISK_DOMAINS[value] || value || '未知方向'
}

export function statusLabel(value) {
  return EVENT_STATUSES[value] || value || '未知状态'
}

export function displayValueLabel(value) {
  return EVENT_STATUSES[value]
    || RISK_LEVELS[value]?.label
    || SOURCE_MODES[value]?.label
    || VALUE_LABELS[value]
    || value
    || '未提供'
}

export function evidenceTypeLabel(value) {
  return EVIDENCE_TYPE_LABELS[value] || value || '未知证据'
}

export function timeScaleLabel(value) {
  return TIME_SCALE_LABELS[value] || value || '摘要'
}

export function unitLabel(value) {
  return UNIT_LABELS[value] || value || ''
}

export function locationLabel(value) {
  return LOCATION_LABELS[value] || value || '未提供'
}

export function zoneIdentifierLabel(value) {
  return ZONE_IDENTIFIER_LABELS[value] || value || '未命名区域'
}

export function feedbackTone(value) {
  const text = String(value || '')
  if (/(正常|确认|无需)/.test(text)) return 'positive'
  if (/(无法|风险|转人工)/.test(text)) return 'risk'
  return 'attention'
}
