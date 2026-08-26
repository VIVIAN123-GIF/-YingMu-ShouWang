export const RISK_DOMAINS = Object.freeze({
  FALL: '跌倒风险',
  MENTAL: '心理趋势',
  FRAUD: '高风险交互',
  SYSTEM: '系统状态',
})

export const RISK_LEVELS = Object.freeze({
  GREEN: { label: '绿色 · 状态平稳', color: '#2f855a', icon: 'CircleCheckFilled' },
  YELLOW: { label: '黄色 · 建议关注', color: '#b7791f', icon: 'WarningFilled' },
  ORANGE: { label: '橙色 · 需要干预', color: '#c05621', icon: 'WarnTriangleFilled' },
  RED: { label: '红色 · 人工接管', color: '#c53030', icon: 'CircleCloseFilled' },
})

export const EVENT_STATUSES = Object.freeze({
  OPEN: '等待处理',
  INTERVENING: '正在干预',
  OBSERVING: '观察期',
  RESOLVED: '已回落',
  ESCALATED: '人工接管',
  FALSE_ALARM: '已确认误报',
})

export const SOURCE_MODES = Object.freeze({
  LIVE_DEVICE: { label: '实时设备', tone: 'success' },
  RECORDED_REPLAY: { label: '授权回放', tone: 'warning' },
  PUBLIC_DATASET: { label: '公开数据集', tone: 'info' },
  MOCK: { label: '模拟接口', tone: 'info' },
})

export const DELIVERY_STATUSES = Object.freeze({
  SUCCESS: { label: 'SUCCESS · 已送达', type: 'success' },
  FAILED: { label: 'FAILED · 调用失败', type: 'danger' },
  RETRYING: { label: 'RETRYING · 正在重试', type: 'warning' },
})

export const DATA_MODES = Object.freeze({
  auto: '自动切换',
  api: '仅 FastAPI',
  replay: '离线授权回放',
})

export const ALARM_TASK_STATUSES = Object.freeze({
  PENDING: { label: '已接收设备告警，等待处理', type: 'info' },
  PROCESSING: { label: '正在调用萤石抓图', type: 'primary' },
  WAITING_ALGORITHM: { label: '平台取证完成，等待算法分析', type: 'info' },
  RETRY: { label: '抓图失败，正在重试', type: 'warning' },
  FAILED: { label: '平台取证失败', type: 'danger' },
})

/**
 * @typedef {'FALL'|'MENTAL'|'FRAUD'|'SYSTEM'} RiskDomain
 * @typedef {'GREEN'|'YELLOW'|'ORANGE'|'RED'} RiskLevel
 * @typedef {'OPEN'|'INTERVENING'|'OBSERVING'|'RESOLVED'|'ESCALATED'|'FALSE_ALARM'} EventStatus
 * @typedef {'LIVE_DEVICE'|'RECORDED_REPLAY'|'PUBLIC_DATASET'} SourceMode
 * @typedef {'SUCCESS'|'FAILED'|'RETRYING'} DeliveryStatus
 */
