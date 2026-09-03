import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TechnicalDisclosure from '../components/common/TechnicalDisclosure.vue'

describe('统一完整运营视图', () => {
  it('技术披露默认收起，点击后展示完整内容并更新状态', async () => {
    const wrapper = mount(TechnicalDisclosure, {
      props: { title: '证据详情', summary: '规则与质量信息' },
      slots: { default: '<div data-testid="details">完整证据</div>' },
    })
    expect(wrapper.find('[data-testid="details"]').exists()).toBe(false)
    expect(wrapper.find('.technical-disclosure-content').exists()).toBe(false)
    expect(wrapper.get('.technical-disclosure-trigger').attributes('aria-expanded')).toBe('false')
    expect(wrapper.get('.technical-disclosure-trigger').text()).toContain('展开')

    await wrapper.get('.technical-disclosure-trigger').trigger('click')

    expect(wrapper.get('[data-testid="details"]').text()).toBe('完整证据')
    expect(wrapper.get('.technical-disclosure-content').exists()).toBe(true)
    expect(wrapper.get('.technical-disclosure-trigger').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('.technical-disclosure-trigger').text()).toContain('收起')
    expect(wrapper.get('.technical-disclosure').attributes('aria-label')).toBe('证据详情')
  })
})
