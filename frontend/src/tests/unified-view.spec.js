import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TechnicalDisclosure from '../components/common/TechnicalDisclosure.vue'

describe('统一完整运营视图', () => {
  it('技术披露内容默认展开且不显示折叠按钮', () => {
    const wrapper = mount(TechnicalDisclosure, {
      props: { title: '证据详情', summary: '规则与质量信息' },
      slots: { default: '<div data-testid="details">完整证据</div>' },
    })
    expect(wrapper.get('[data-testid="details"]').text()).toBe('完整证据')
    expect(wrapper.find('.technical-disclosure-trigger').exists()).toBe(false)
    expect(wrapper.get('.technical-disclosure').attributes('aria-label')).toBe('证据详情')
  })
})
