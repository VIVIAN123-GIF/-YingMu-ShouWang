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
  normal_baseline_sample: '日常稳定基线样本',
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
  'living-room-activity-safe': '客厅活动安全区',
  'hallway-doorway-risk': '走廊门口高风险区',
  'sofa-seating-support': '沙发坐席支撑区',
  'dining-cabinet-obstacle': '餐边柜障碍区',
})

const SCENE_CONFIG_LABELS = Object.freeze({
  'living-room-c6c-20260831': '客厅 C6c 场景配置（2026-08-31）',
  'scene-replay-living-room': '客厅授权回放场景',
})

const CAMERA_POSITION_LABELS = Object.freeze({
  'living-room-new-position-01': '客厅新机位 01',
  'recorded-fixed-demo-v1': '授权回放固定机位（版本 1）',
  'living-room-main': '客厅主机位',
  'baseline-video-package': '个人基线授权视频固定机位',
})

const SCHEMA_VERSION_LABELS = Object.freeze({
  'scene-calibration/1.0': '场景标定协议 1.0',
})

const RULE_LABELS = Object.freeze({
  'R-FALL-01': '起身不稳初筛规则',
  'R-FALL-02': '起身后摇晃规则',
  'R-FALL-03': '多信号不稳定橙色干预规则',
  'R-FALL-04': '干预后姿态恢复规则',
  'R-MENTAL-01': '活动范围变化规则',
  'R-FRAUD-01': '访客身份核验规则',
})

const ADAPTER_VERSION_LABELS = Object.freeze({
  'gait-adapter-v1.2': '步态分析适配器 1.2',
  'environment-adapter-v1': '环境分析适配器 1.0',
  'behavior-adapter-v1': '行为分析适配器 1.0',
  'visitor-adapter-v1': '访客分析适配器 1.0',
  'audio-adapter-v1': '音频分析适配器 1.0',
  'device-adapter-v1': '设备状态适配器 1.0',
})

const MEDIA_TITLE_LABELS = Object.freeze({
  'Authorized simulated living-room replay': '授权模拟客厅回放',
})

const DEVICE_MODEL_LABELS = Object.freeze({
  EZVIZ_C6C: '萤石 C6c 摄像机',
  C6C: '萤石 C6c 摄像机',
})

const ERROR_CODE_LABELS = Object.freeze({
  REQUEST_FAILED: '请求失败',
  CONTROL_FORBIDDEN: '没有设备控制权限',
  CONTROL_TOKEN_REQUIRED: '需要现场控制令牌',
  LIVE_CONTROL_UNAVAILABLE: '当前设备不可远程控制',
  CONTROL_REQUEST_FAILED: '设备控制请求失败',
  SCENE_CONFIG_MISSING: '未找到场景标定',
  SCENE_CONFIG_REQUIRED: '缺少场景标定',
  SCENE_CONFIG_INVALID: '场景标定无效',
  MEDIA_REQUEST_FAILED: '媒体加载失败',
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
  mock_voice: '本地语音提醒',
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
  sat_down: '老人已坐稳',
  none: '无需操作',
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
  if (!value) return '暂无可追溯视频'
  const numericId = String(value).match(/^asset-(\d+)$/i)?.[1]
  if (numericId) return `受控素材 ${numericId}`
  if (/^[A-Za-z][A-Za-z0-9_-]*$/.test(String(value))) return '受控素材记录'
  return value
}

export function mediaTitleLabel(value) {
  const title = String(value || '').trim()
  const unavailableMatch = /^Simulated unavailable media \(([^)]+)\)$/i.exec(title)
  if (unavailableMatch) return '模拟媒体暂不可用'
  return MEDIA_TITLE_LABELS[title] || title || '事件画面'
}

export function mediaNoticeLabel(value) {
  const notice = String(value || '').trim()
  if (notice === 'Simulated metadata only; no private media is stored.') return '仅模拟元数据，无实际媒体录像存储'
  if (/^[\x00-\x7F]+$/.test(notice) && /[A-Za-z]/.test(notice)) return '媒体说明暂不可用'
  return notice
}

export function domainLabel(value) {
  return RISK_DOMAINS[value] || '其他风险方向'
}

export function statusLabel(value) {
  return EVENT_STATUSES[value] || '未知状态'
}

export function displayValueLabel(value) {
  const mapped = EVENT_STATUSES[value]
    || RISK_LEVELS[value]?.label
    || SOURCE_MODES[value]?.label
    || VALUE_LABELS[value]
  if (mapped) return mapped
  if (!value) return '未提供'
  if (/^ruleset-/i.test(String(value))) return rulesetVersionLabel(value)
  if (/^[A-Za-z][A-Za-z0-9_-]*$/.test(String(value))) return '其他信息'
  return value
}

export function evidenceTypeLabel(value) {
  return EVIDENCE_TYPE_LABELS[value]
    || (/^[A-Za-z][A-Za-z0-9_-]*$/.test(String(value || '')) ? '其他分析依据' : value)
    || '未知证据'
}

export function timeScaleLabel(value) {
  return TIME_SCALE_LABELS[value] || '摘要'
}

export function unitLabel(value) {
  return UNIT_LABELS[value] || ''
}

export function locationLabel(value) {
  return LOCATION_LABELS[value]
    || (/^[A-Za-z][A-Za-z0-9_-]*$/.test(String(value || '')) ? '其他区域' : value)
    || '未提供'
}

export function zoneIdentifierLabel(value) {
  return ZONE_IDENTIFIER_LABELS[value]
    || (/^[A-Za-z][A-Za-z0-9_-]*$/.test(String(value || '')) ? '未命名区域' : value)
    || '未命名区域'
}

export function sceneConfigLabel(value) {
  return SCENE_CONFIG_LABELS[value]
    || (/^[A-Za-z][A-Za-z0-9_-]*$/.test(String(value || '')) ? '当前场景配置' : value)
    || '未命名场景配置'
}

export function cameraPositionLabel(value) {
  return CAMERA_POSITION_LABELS[value]
    || (/^[A-Za-z][A-Za-z0-9_-]*$/.test(String(value || '')) ? '固定摄像机位' : value)
    || '未命名摄像机位'
}

export function schemaVersionLabel(value) {
  return SCHEMA_VERSION_LABELS[value]
    || (/^[A-Za-z][A-Za-z0-9_./-]*$/.test(String(value || '')) ? '场景标定协议' : value)
    || '未提供'
}

export function ruleLabel(value) {
  return RULE_LABELS[value]
    || (/^R-[A-Z]+-\d+$/i.test(String(value || '')) ? `风险判断规则 ${String(value).split('-').at(-1)}` : value)
    || '未知规则'
}

export function adapterVersionLabel(value) {
  return ADAPTER_VERSION_LABELS[value]
    || (/^[A-Za-z][A-Za-z0-9_.-]*$/.test(String(value || '')) ? '分析适配器' : value)
    || '未提供'
}

export function rulesetVersionLabel(value) {
  const version = String(value || '').match(/^ruleset-v?(.+)$/i)?.[1]
  if (!version) return value || '未提供'
  return `风险规则集 ${version.replace(/-min$/i, '（精简版）')}`
}

export function residentIdentifierLabel(value) {
  const numericId = String(value || '').match(/^resident-(\d+)$/i)?.[1]
  return numericId ? `居民档案 ${numericId}` : '当前居民档案'
}

export function eventIdentifierLabel(value) {
  const text = String(value || '')
  const numericId = text.match(/(?:^|-)event-[^-]*-(\d+)$/i)?.[1] || text.match(/(\d+)$/)?.[1]
  const traceId = text.match(/(?:^|-)([a-f\d]{6,})(?:-|$)/i)?.[1]
  if (numericId) return `事件记录 ${numericId}`
  if (traceId) return `事件记录（尾码 ${traceId.slice(-8).toUpperCase()}）`
  return '当前事件记录'
}

export function evidenceIdentifierLabel(value) {
  const text = String(value || '')
  const suffix = text.match(/([a-f\d]{6,})$/i)?.[1] || text.match(/(\d+)$/)?.[1]
  return suffix ? `依据记录（尾码 ${suffix.slice(-8).toUpperCase()}）` : '当前依据记录'
}

export function observationIdentifierLabel(value) {
  const text = String(value || '')
  const suffix = text.match(/([a-f\d]{6,})$/i)?.[1] || text.match(/(\d+)$/)?.[1]
  return suffix ? `观测记录（尾码 ${suffix.slice(-8).toUpperCase()}）` : '当前观测记录'
}

export function alarmIdentifierLabel(value) {
  const text = String(value || '')
  const suffix = text.match(/([a-f\d]{6,})$/i)?.[1] || text.match(/(\d+)$/)?.[1]
  return suffix ? `设备告警任务（尾码 ${suffix.slice(-8).toUpperCase()}）` : '设备告警任务'
}

export function deviceModelLabel(value) {
  const text = String(value || '')
  if (DEVICE_MODEL_LABELS[text]) return DEVICE_MODEL_LABELS[text]
  if (/ezviz.*c6c|c6c.*ezviz/i.test(text)) return '萤石 C6c 摄像机'
  if (/^[A-Za-z][A-Za-z0-9_.-]*$/.test(text)) return '摄像设备'
  return text || '未提供'
}

export function explanationSourceLabel(value) {
  const text = String(value || '')
  if (/^template-fallback/i.test(text)) return '系统备用解释模板'
  if (/^replay-explanation/i.test(text)) return '授权回放解释'
  if (/^qwen/i.test(text)) return '智能解释模型'
  return text ? '智能解释服务' : '未提供'
}

export function errorCodeLabel(value) {
  return ERROR_CODE_LABELS[value] || (value ? '服务请求异常' : '未知错误')
}

export function resolutionReasonLabel(value) {
  const text = String(value || '').trim()
  if (text === 'Declared Mock fallback') return '已使用备用提醒流程'
  if (/^[\x00-\x7F]+$/.test(text) && /[A-Za-z]/.test(text)) return '已按备用流程处理'
  return text || '等待结果'
}

export function deviceAliasLabel(value) {
  const alias = String(value || '')
  const liveMatch = /^camera-live(?:-(\d+))?$/i.exec(alias)
  if (liveMatch) return `实时摄像机${liveMatch[1] ? ` ${liveMatch[1]}` : ''}`
  const replayMatch = /^camera-(?:mock|replay)(?:-(\d+))?$/i.exec(alias)
  if (replayMatch) return `回放摄像机${replayMatch[1] ? ` ${replayMatch[1]}` : ''}`
  return displayValueLabel(value)
}

export function deviceReferenceLabel(value) {
  const reference = String(value || '')
  const suffix = reference.match(/([a-f\d]{6,})$/i)?.[1] || reference.match(/(\d+)$/)?.[1]
  if (/^device-/i.test(reference) && suffix) return `当前摄像设备（尾码 ${suffix.slice(-8).toUpperCase()}）`
  if (/^device-/i.test(reference)) return '当前摄像设备'
  return displayValueLabel(value)
}

export function feedbackTone(value) {
  const text = String(value || '')
  if (/(正常|确认|无需)/.test(text)) return 'positive'
  if (/(无法|风险|转人工)/.test(text)) return 'risk'
  return 'attention'
}
