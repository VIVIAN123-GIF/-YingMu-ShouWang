import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import forewarning from '../replay-data/forewarning.json'

const mocks = vi.hoisted(() => ({ getDashboard: vi.fn(), getLatestForewarning: vi.fn(), getForewarningHistory: vi.fn() }))
vi.mock('../services/repository', () => ({
  getDashboard: mocks.getDashboard, getLatestForewarning: mocks.getLatestForewarning,
  getForewarningHistory: mocks.getForewarningHistory,
}))

import ResidentView from '../views/ResidentView.vue'

function mountView() {
  return mount(ResidentView, { global: {
    directives: { loading: () => {} },
    stubs: {
      PageHeader: { template: '<header><slot /></header>' }, SourceBadge: { template: '<span class="source-stub" />' },
      ChartPanel: { template: '<div class="chart-stub" />' },
      'el-alert': { props: ['title'], template: '<div class="alert-stub">{{ title }}</div>' },
      'el-empty': { props: ['description'], template: '<div class="empty-stub">{{ description }}</div>' },
      'el-tag': { template: '<span><slot /></span>' }, 'el-avatar': { template: '<span><slot /></span>' },
      'el-segmented': { template: '<div class="segmented-stub" />' }, 'el-date-picker': { template: '<input />' },
      'el-button': { template: '<button><slot /></button>' },
      'el-table': { name: 'ElTableStub', props: ['data'], template: '<div class="table-stub">{{ data.length }} rows<slot /></div>' },
      'el-table-column': { template: '<span />' },
      'el-pagination': { props: ['total'], template: '<div class="pagination-stub">total {{ total }}</div>' },
      'el-form': { template: '<form><slot /></form>' }, 'el-form-item': { template: '<label><slot /></label>' },
      'el-input': { template: '<input />' }, 'el-checkbox': { template: '<label><slot /></label>' },
    },
  } })
}

function historyOf(count) {
  return Array.from({ length: count }, (_, index) => ({
    ...structuredClone(forewarning[index % forewarning.length]),
    snapshot_id: `history-${index}`,
    evaluated_at: new Date(Date.parse('2026-08-26T19:00:00+08:00') - index * 60_000).toISOString(),
  }))
}

describe('居民预警汇总页面', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset())
    mocks.getDashboard.mockResolvedValue({ resident: { resident_id: 'resident-001' }, device: { source_mode: 'RECORDED_REPLAY', simulated: true } })
  })

  it('最新预警和历史均为空时展示独立空状态', async () => {
    mocks.getLatestForewarning.mockResolvedValue(null)
    mocks.getForewarningHistory.mockResolvedValue([])
    const wrapper = mountView(); await flushPromises()
    expect(wrapper.text()).toContain('当前居民暂无预警摘要')
    expect(wrapper.text()).toContain('所选时间范围内暂无预警历史')
  })

  it('部分数据展示最新摘要、趋势和完整当前页', async () => {
    const items = historyOf(2)
    mocks.getLatestForewarning.mockResolvedValue(items[0])
    mocks.getForewarningHistory.mockResolvedValue(items)
    const wrapper = mountView(); await flushPromises()
    expect(wrapper.text()).toContain(items[0].ruleset_version)
    expect(wrapper.find('.chart-stub').exists()).toBe(true)
    expect(wrapper.text()).toContain('2 rows')
    expect(wrapper.find('.pagination-stub').exists()).toBe(false)
  })

  it('历史记录按发生时间升序排列', async () => {
    const items = historyOf(2)
    mocks.getLatestForewarning.mockResolvedValue(items[0])
    mocks.getForewarningHistory.mockResolvedValue(items)
    const wrapper = mountView(); await flushPromises()
    const rows = wrapper.findComponent({ name: 'ElTableStub' }).props('data')
    expect(rows.map((item) => item.snapshot_id)).toEqual(['history-1', 'history-0'])
  })

  it('500条历史使用固定20条当前页和分页布局', async () => {
    const items = historyOf(500)
    mocks.getLatestForewarning.mockResolvedValue(items[0])
    mocks.getForewarningHistory.mockResolvedValue(items)
    const wrapper = mountView(); await flushPromises()
    expect(wrapper.text()).toContain('500 条')
    expect(wrapper.text()).toContain('20 rows')
    expect(wrapper.text()).toContain('total 500')
  })

  it('档案接口失败不阻塞最新预警展示', async () => {
    mocks.getDashboard.mockRejectedValue(new Error('profile unavailable'))
    mocks.getLatestForewarning.mockResolvedValue(structuredClone(forewarning[0]))
    mocks.getForewarningHistory.mockResolvedValue([])
    const wrapper = mountView(); await flushPromises()
    expect(wrapper.text()).toContain('无法读取老人档案')
    expect(wrapper.text()).toContain(forewarning[0].ruleset_version)
  })
})
