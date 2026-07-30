import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import baselineMock from '../mocks/baseline.json'
import { normalizeBaseline } from '../services/viewModel'

const { getBaselineMock } = vi.hoisted(() => ({ getBaselineMock: vi.fn() }))

vi.mock('../services/repository', () => ({ getBaseline: getBaselineMock }))

import BaselineView from '../views/BaselineView.vue'

function mountView() {
  return mount(BaselineView, {
    global: {
      directives: { loading: () => {} },
      stubs: {
        PageHeader: { template: '<header><slot /></header>' },
        SourceBadge: { template: '<span class="source-stub" />' },
        ChartPanel: { template: '<div class="chart-stub" />' },
        'el-alert': { props: ['title'], template: '<div class="alert-stub">{{ title }}<slot /></div>' },
        'el-empty': { props: ['description'], template: '<div class="empty-stub">{{ description }}</div>' },
        'el-progress': { template: '<div class="progress-stub"><slot name="default" :percentage="100" /></div>' },
        'el-tag': { template: '<span><slot /></span>' },
      },
    },
  })
}

describe('个人基线页面', () => {
  beforeEach(() => getBaselineMock.mockReset())

  it('Mock 模式展示三种基线状态、趋势和模拟热力图', async () => {
    getBaselineMock.mockResolvedValue(normalizeBaseline(structuredClone(baselineMock)))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('稳定基线')
    expect(wrapper.text()).toContain('暂定基线')
    expect(wrapper.text()).toContain('样本不足')
    expect(wrapper.text()).toContain('模拟实验回放')
    expect(wrapper.findAll('.chart-stub')).toHaveLength(2)
  })

  it('API 没有时序数据时展示诚实空状态', async () => {
    getBaselineMock.mockResolvedValue(normalizeBaseline({
      resident_id: 'resident-api', as_of: '2026-07-30T08:00:00+08:00', ruleset_version: 'ruleset-v1.0',
      source_mode: 'MOCK', simulated: true,
      baselines: { rise_duration: { median: 3.5, mad: 0.4, sample_count: 20, distinct_days: 7, status: 'STABLE' } },
    }))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('当前 API 未提供活动时序数据，不使用 Mock 趋势补位')
    expect(wrapper.text()).toContain('当前 API 暂无活动热力图时序数据')
    expect(wrapper.text()).not.toContain('模拟实验回放')
  })
})
