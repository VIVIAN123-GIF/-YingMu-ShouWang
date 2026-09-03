import { describe, expect, it } from 'vitest'
import { DATA_MODES, DELIVERY_STATUSES, EVENT_STATUSES, RISK_LEVELS, SOURCE_MODES } from '../domain/constants'
import { shouldFallback } from '../services/repository'
import { DataContractError, validateDashboard, validateForewarningSnapshot } from '../domain/validation'
import { deviceAliasLabel, deviceModelLabel, displayValueLabel, evidenceTypeLabel, explanationSourceLabel, locationLabel, mediaTitleLabel, residentIdentifierLabel, rulesetVersionLabel, timeScaleLabel, unitLabel, zoneIdentifierLabel } from '../utils/format'

describe('冻结枚举', () => {
  it('保留四级风险、六种事件状态和四种来源', () => {
    expect(Object.keys(RISK_LEVELS)).toEqual(['GREEN', 'YELLOW', 'ORANGE', 'RED'])
    expect(Object.keys(EVENT_STATUSES)).toEqual(['OPEN', 'INTERVENING', 'OBSERVING', 'RESOLVED', 'ESCALATED', 'FALSE_ALARM'])
    expect(Object.keys(SOURCE_MODES)).toEqual(['LIVE_DEVICE', 'RECORDED_REPLAY', 'PUBLIC_DATASET', 'MOCK'])
    expect(DATA_MODES.api).toBe('实时连接')
  })

  it('工具失败不会映射成成功', () => {
    expect(DELIVERY_STATUSES.FAILED.type).toBe('danger')
    expect(DELIVERY_STATUSES.FAILED.label).toBe('调用失败')
    expect(DELIVERY_STATUSES.FAILED.label).not.toContain('成功')
  })
})

describe('用户可见枚举中文化', () => {
  it('翻译状态、来源、证据、时间尺度和单位', () => {
    expect(displayValueLabel('VALID')).toBe('完整评估')
    expect(displayValueLabel('RECORDED_REPLAY')).toBe('授权回放')
    expect(evidenceTypeLabel('activity_range_decline')).toBe('活动范围下降')
    expect(timeScaleLabel('LONG')).toBe('长期')
    expect(unitLabel('second')).toBe('秒')
  })

  it('将技术标识转换为用户可理解的中文', () => {
    expect(displayValueLabel('ruleset-v2')).toBe('风险规则集 2')
    expect(rulesetVersionLabel('ruleset-v1.3-min')).toBe('风险规则集 1.3（精简版）')
    expect(residentIdentifierLabel('resident-001')).toBe('居民档案 001')
    expect(deviceAliasLabel('camera-live-001')).toBe('实时摄像机 001')
    expect(deviceModelLabel('EZVIZ_C6C')).toBe('萤石 C6c 摄像机')
    expect(explanationSourceLabel('template-fallback-v1')).toBe('系统备用解释模板')
    expect(displayValueLabel('sat_down')).toBe('老人已坐稳')
    expect(displayValueLabel('UNMAPPED_TECHNICAL_VALUE')).toBe('其他信息')
  })

  it('将模拟媒体的用户可见标题转换为中文，保留素材标识', () => {
    expect(mediaTitleLabel('Simulated unavailable media (asset-fall-authorized)')).toBe('模拟媒体暂不可用')
  })
})

describe('Display label localization', () => {
  it('shows common locations and configured zone identifiers in Chinese', () => {
    expect(locationLabel('living_room')).toBe('客厅')
    expect(locationLabel('bedroom')).toBe('卧室')
    expect(zoneIdentifierLabel('fixed-chair-support')).toBe('固定座椅支撑区')
    expect(evidenceTypeLabel('normal_baseline_sample')).toBe('日常稳定基线样本')
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
      resident_id: 'resident-test', evaluated_at: '2026-08-26T19:00:00+08:00', phase: 'PERIODIC',
      assessment_status: 'VALID', confidence_level: 'HIGH', baseline_status: 'STABLE',
      components: { human_risk: 0.7, personal_deviation: 0.2, environment_risk: 0.1, interaction_risk: 0.3 },
      instant: { engineering_index: 0.7, attention_level: 'ORANGE' },
      short_30s: { engineering_index: 0.6, attention_level: 'YELLOW' },
      trend_3min: { engineering_index: 0.5, attention_level: 'YELLOW' },
      recommended_action: '继续观察。', ruleset_version: 'ruleset-v1.3-min', source_mode: 'MOCK', simulated: true,
    }
    expect(validateForewarningSnapshot(snapshot)).toBe(snapshot)
  })
})
