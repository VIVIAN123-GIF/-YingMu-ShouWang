import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReplaySelector from '../components/replay/ReplaySelector.vue'

describe('统一事件影像选择器', () => {
  it('合并显示标题相同的事件，并优先保留真实设备记录', () => {
    const wrapper = mount(ReplaySelector, {
      props: {
        events: [
          { event_id: 'event-a', title: '  起身活动 ', source_mode: 'RECORDED_REPLAY', simulated: true, created_at: '2026-08-01T08:00:00+08:00' },
          { event_id: 'event-b', title: '起身活动', source_mode: 'LIVE_DEVICE', simulated: false, created_at: '2026-08-01T07:00:00+08:00' },
          { event_id: 'event-c', title: '日常步行', source_mode: 'RECORDED_REPLAY', simulated: true, created_at: '2026-08-01T09:00:00+08:00' },
        ],
      },
      global: { stubs: {
        'el-icon': { template: '<span><slot /></span>' },
        'el-select': { template: '<div><slot /></div>' },
        'el-option': { props: ['label', 'value'], template: '<span class="option" :data-value="value">{{ label }}</span>' },
      } },
    })

    expect(wrapper.findAll('.option')).toHaveLength(2)
    expect(wrapper.findAll('.option').map((option) => option.attributes('data-value'))).toEqual(['event-b', 'event-c'])
    expect(wrapper.findAll('.option').map((option) => option.text())).toEqual(['1. 起身活动', '2. 日常步行'])
  })
})
