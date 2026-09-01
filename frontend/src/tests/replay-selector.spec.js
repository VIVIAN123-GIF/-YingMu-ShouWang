import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReplaySelector from '../components/replay/ReplaySelector.vue'

describe('统一事件影像选择器', () => {
  it('保留标题相同但 event_id 不同的事件', () => {
    const wrapper = mount(ReplaySelector, {
      props: {
        events: [
          { event_id: 'event-a', title: '起身活动' },
          { event_id: 'event-b', title: '起身活动' },
        ],
      },
      global: { stubs: {
        'el-icon': { template: '<span><slot /></span>' },
        'el-select': { template: '<div><slot /></div>' },
        'el-option': { props: ['label', 'value'], template: '<span class="option" :data-value="value">{{ label }}</span>' },
      } },
    })

    expect(wrapper.findAll('.option')).toHaveLength(2)
    expect(wrapper.findAll('.option').map((option) => option.attributes('data-value'))).toEqual(['event-a', 'event-b'])
  })
})
