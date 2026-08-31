import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import baselineMock from '../replay-data/baseline.json'
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
        ActivityHeatmap: { template: '<div class="heatmap-stub" />' },
        'el-alert': { props: ['title'], template: '<div class="alert-stub">{{ title }}<slot /></div>' },
        'el-empty': { props: ['description'], template: '<div class="empty-stub">{{ description }}</div>' },
        'el-progress': { template: '<div class="progress-stub"><slot name="default" :percentage="100" /></div>' },
        'el-tag': { template: '<span><slot /></span>' },
      },
    },
  })
}

describe('个人基线页面', () => {
  beforeEach(() => { getBaselineMock.mockReset() })

  it('授权回放展示实验覆盖且不冒充居民个人基线', async () => {
    getBaselineMock.mockResolvedValue(normalizeBaseline(structuredClone(baselineMock)))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('3 / 3 个初步有效日')
    expect(wrapper.text()).toContain('0.60 秒')
    expect(wrapper.text()).toContain('0.75 米/秒')
    expect(wrapper.text()).toContain('2.90 度')
    expect(wrapper.text()).not.toContain('待个人校准')
    expect(wrapper.findAll('.chart-stub')).toHaveLength(1)
    expect(wrapper.findAll('.heatmap-stub')).toHaveLength(1)
  })

  it('API 没有时序数据时展示诚实空状态', async () => {
    getBaselineMock.mockResolvedValue(normalizeBaseline({
      resident_id: 'resident-api', as_of: '2026-07-30T08:00:00+08:00', ruleset_version: 'ruleset-v1.0',
      source_mode: 'RECORDED_REPLAY', simulated: true,
      baselines: { rise_duration: { median: 3.5, mad: 0.4, sample_count: 20, distinct_days: 7, status: 'STABLE' } },
    }))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('暂无活动趋势数据')
    expect(wrapper.text()).toContain('暂无活动热力图数据')
    expect(wrapper.text()).not.toContain('模拟实验回放')
  })
})
