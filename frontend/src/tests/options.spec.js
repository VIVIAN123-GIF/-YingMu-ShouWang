import { describe, expect, it } from 'vitest'
import { RISK_LEVELS, SOURCE_MODES } from '../domain/constants'
import { groupOptionsByLabel, matchesGroupedOption, uniqueTextOptions } from '../utils/options'

describe('visible option deduplication', () => {
  it('keeps only one identical text option', () => {
    expect(uniqueTextOptions(['已联系', '已联系', '暂时无法联系'])).toEqual(['已联系', '暂时无法联系'])
  })

  it('groups duplicate risk and source labels without losing their raw values', () => {
    const riskOptions = groupOptionsByLabel(RISK_LEVELS, (config) => config.label)
    const sourceOptions = groupOptionsByLabel(SOURCE_MODES, (config) => config.label)

    expect(riskOptions.filter((option) => option.label === '高风险')).toHaveLength(1)
    expect(matchesGroupedOption(riskOptions, 'ORANGE', 'RED')).toBe(true)
    expect(sourceOptions.filter((option) => option.label === '授权回放')).toHaveLength(1)
    expect(matchesGroupedOption(sourceOptions, 'RECORDED_REPLAY', 'MOCK')).toBe(true)
  })
})
