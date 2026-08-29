import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SourceBadge from '../components/common/SourceBadge.vue'
import RiskBadge from '../components/common/RiskBadge.vue'

describe('来源与风险标识', () => {
  it('模拟回放只向用户展示中文来源和水印', () => {
    const wrapper = mount(SourceBadge, { props: { mode: 'RECORDED_REPLAY', simulated: true } })
    expect(wrapper.text()).toContain('授权回放')
    expect(wrapper.text()).toContain('模拟实验回放')
    expect(wrapper.text()).not.toContain('RECORDED_REPLAY')
  })

  it('黄色风险使用低打扰语义', () => {
    const wrapper = mount(RiskBadge, { props: { level: 'YELLOW' } })
    expect(wrapper.text()).toContain('建议关注')
  })

  it('未知等级不会静默显示为绿色', () => {
    const wrapper = mount(RiskBadge, { props: { level: 'UNKNOWN', score: 0 } })
    expect(wrapper.text()).toContain('不可判定')
    expect(wrapper.text()).toContain('人工复核')
    expect(wrapper.text()).not.toContain('状态平稳')
    expect(wrapper.find('.risk-score').exists()).toBe(false)
    expect(wrapper.find('.risk-unknown-mark').exists()).toBe(false)
    expect(wrapper.attributes('aria-label')).not.toContain('风险分数0')
  })
})
