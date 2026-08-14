import { describe, expect, it } from 'vitest'
import { DELIVERY_STATUSES, EVENT_STATUSES, RISK_LEVELS, SOURCE_MODES } from '../domain/constants'
import { shouldFallback } from '../services/repository'
import { DataContractError } from '../domain/validation'

describe('冻结枚举', () => {
  it('保留四级风险、五种事件状态和四种来源', () => {
    expect(Object.keys(RISK_LEVELS)).toEqual(['GREEN', 'YELLOW', 'ORANGE', 'RED'])
    expect(Object.keys(EVENT_STATUSES)).toEqual(['OPEN', 'INTERVENING', 'OBSERVING', 'RESOLVED', 'ESCALATED'])
    expect(Object.keys(SOURCE_MODES)).toEqual(['LIVE_DEVICE', 'RECORDED_REPLAY', 'PUBLIC_DATASET', 'MOCK'])
  })

  it('工具失败不会映射成成功', () => {
    expect(DELIVERY_STATUSES.FAILED.type).toBe('danger')
    expect(DELIVERY_STATUSES.FAILED.label).toContain('FAILED')
    expect(DELIVERY_STATUSES.FAILED.label).not.toContain('成功')
  })
})

describe('FastAPI 自动降级边界', () => {
  it.each([404, 501, 500, 503])('HTTP %s 可进入固定 JSON 降级', (status) => {
    expect(shouldFallback({ response: { status } })).toBe(true)
  })

  it('网络不可达可降级，数据与权限错误不可静默降级', () => {
    expect(shouldFallback({ message: 'Network Error' })).toBe(true)
    expect(shouldFallback({ response: { status: 400 } })).toBe(false)
    expect(shouldFallback({ response: { status: 403 } })).toBe(false)
    expect(shouldFallback(new DataContractError('risk_score越界'))).toBe(false)
  })
})
