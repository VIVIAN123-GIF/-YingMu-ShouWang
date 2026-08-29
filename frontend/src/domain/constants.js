export const RISK_DOMAINS = Object.freeze({
  FALL: '跌倒风险',
  MENTAL: '心理趋势',
  FRAUD: '高风险交互',
  SYSTEM: '系统状态',
})

export const RISK_LEVELS = Object.freeze({
  GREEN: { label: '低风险', color: '#00B42A', icon: 'CircleCheckFilled' },
  YELLOW: { label: '中风险', color: '#FF7D00', icon: 'WarningFilled' },
  ORANGE: { label: '高风险', color: '#F53F3F', icon: 'WarnTriangleFilled' },
  RED: { label: '高风险', color: '#F53F3F', icon: 'CircleCloseFilled' },
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
  PUBLIC_DATASET: { label: '授权回放', tone: 'warning' },
  MOCK: { label: '授权回放', tone: 'warning' },
})

export const DELIVERY_STATUSES = Object.freeze({
  SUCCESS: { label: '已送达', type: 'success' },
  FAILED: { label: '调用失败', type: 'danger' },
  RETRYING: { label: '正在重试', type: 'warning' },
})

export const DATA_MODES = Object.freeze({
  auto: '自动切换',
  api: '实时连接',
  replay: '离线回放',
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
 * @typedef {'LIVE_DEVICE'|'RECORDED_REPLAY'|'PUBLIC_DATASET'|'MOCK'} SourceMode
 * @typedef {'SUCCESS'|'FAILED'|'RETRYING'} DeliveryStatus
 */
