import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SourceBadge from '../components/common/SourceBadge.vue'
import RiskBadge from '../components/common/RiskBadge.vue'

describe('来源与风险标识', () => {
  it('模拟回放同时显示机器枚举和用户水印', () => {
    const wrapper = mount(SourceBadge, { props: { mode: 'RECORDED_REPLAY', simulated: true } })
    expect(wrapper.text()).toContain('RECORDED_REPLAY')
    expect(wrapper.text()).toContain('授权回放')
    expect(wrapper.text()).toContain('模拟实验回放')
  })

  it('黄色风险使用低打扰语义', () => {
    const wrapper = mount(RiskBadge, { props: { level: 'YELLOW' } })
    expect(wrapper.text()).toContain('建议关注')
  })
})
