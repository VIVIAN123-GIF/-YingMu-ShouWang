import { describe, expect, it } from 'vitest'
import { DELIVERY_STATUSES, EVENT_STATUSES, RISK_LEVELS, SOURCE_MODES } from '../domain/constants'
import { shouldFallback } from '../services/repository'
import { DataContractError, validateDashboard, validateForewarningSnapshot } from '../domain/validation'

describe('冻结枚举', () => {
  it('保留四级风险、六种事件状态和四种来源', () => {
    expect(Object.keys(RISK_LEVELS)).toEqual(['GREEN', 'YELLOW', 'ORANGE', 'RED'])
    expect(Object.keys(EVENT_STATUSES)).toEqual(['OPEN', 'INTERVENING', 'OBSERVING', 'RESOLVED', 'ESCALATED', 'FALSE_ALARM'])
    expect(Object.keys(SOURCE_MODES)).toEqual(['LIVE_DEVICE', 'RECORDED_REPLAY', 'PUBLIC_DATASET'])
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

describe('前置预警未知状态', () => {
  it('数据不足保留 UNKNOWN，不要求伪装成 GREEN', () => {
    const dashboard = {
      device: { source_mode: 'RECORDED_REPLAY', simulated: true },
      pre_fall_summary: {
        risk_level: 'UNKNOWN', instant_risk: 0, risk_30s: 0, trend_3min: 0,
        trend_direction: 'STABLE', personal_deviation: 0, environment_risk: 0,
        quality_penalty: 1, dominant_factors: ['data_quality_downgrade'],
        evidence_ids: [], recommended_intervention: '等待合格证据。',
      },
    }
    expect(validateDashboard(dashboard).pre_fall_summary.risk_level).toBe('UNKNOWN')
  })

  it('接受合法的前置预警快照枚举', () => {
    const snapshot = {
      schema_version: 'forewarning-snapshot/1.0', snapshot_id: 'snapshot-test',
      assessment_status: 'VALID', confidence_level: 'HIGH', baseline_status: 'STABLE',
      components: { human_risk: 0.7, personal_deviation: 0.2, environment_risk: 0.1, interaction_risk: 0.3 },
      instant: { engineering_index: 0.7, attention_level: 'ORANGE' },
      short_30s: { engineering_index: 0.6, attention_level: 'YELLOW' },
      trend_3min: { engineering_index: 0.5, attention_level: 'YELLOW' },
    }
    expect(validateForewarningSnapshot(snapshot)).toBe(snapshot)
  })
})
