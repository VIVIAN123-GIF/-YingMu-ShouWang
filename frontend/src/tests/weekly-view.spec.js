import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import weeklyMock from '../replay-data/weekly.json'

const { getWeeklyReportMock, submitFamilyFeedbackMock, messageMock } = vi.hoisted(() => ({
  getWeeklyReportMock: vi.fn(),
  submitFamilyFeedbackMock: vi.fn(),
  messageMock: { warning: vi.fn(), success: vi.fn(), error: vi.fn() },
}))

vi.mock('../services/repository', () => ({
  getWeeklyReport: getWeeklyReportMock,
  submitFamilyFeedback: submitFamilyFeedbackMock,
}))

vi.mock('element-plus', async (importOriginal) => ({
  ...(await importOriginal()),
  ElMessage: messageMock,
}))

import WeeklyView from '../views/WeeklyView.vue'

function mountView() {
  return mount(WeeklyView, {
    global: {
      directives: { loading: () => {} },
      stubs: {
        PageHeader: { template: '<header><slot /></header>' },
        RiskBadge: { template: '<span class="risk-badge"><slot /></span>' },
        SourceBadge: { template: '<span class="source-badge"><slot /></span>' },
        ChartPanel: { template: '<div class="chart-stub" />' },
        'el-alert': { props: ['title'], template: '<div class="alert-stub">{{ title }}</div>' },
        'el-empty': { props: ['description'], template: '<div class="empty-stub">{{ description }}</div>' },
        'el-button': {
          props: ['disabled', 'loading'],
          template: '<button :disabled="disabled"><slot /></button>',
        },
        'el-radio-group': { template: '<div><slot /></div>' },
        'el-radio': { props: ['value'], template: '<label><input type="radio" :value="value" /><slot /></label>' },
      },
    },
  })
}

describe('黄色周报与诈骗核验卡', () => {
  beforeEach(() => {
    getWeeklyReportMock.mockReset()
    submitFamilyFeedbackMock.mockReset().mockResolvedValue({ result_id: 'feedback-result' })
    messageMock.warning.mockReset()
    messageMock.success.mockReset()
    messageMock.error.mockReset()
  })

  it('Mock 模式展示黄色趋势、关怀选项和三类诈骗证据，并可分别提交', async () => {
    getWeeklyReportMock.mockResolvedValue(structuredClone(weeklyMock))
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('[data-testid="weekly-summary"]').text()).toContain('建议家属进行一次温和联系')
    expect(wrapper.get('[data-testid="care-panel"]').text()).toContain('已联系，希望继续关注')
    expect(wrapper.get('[data-testid="visitor-panel"]').findAll('.visitor-evidence article')).toHaveLength(3)
    expect(wrapper.get('[data-testid="visitor-panel"]').text()).toContain('高风险组合词')

    wrapper.vm.careChoice = weeklyMock.care.options[0]
    await wrapper.get('[data-testid="care-submit"]').trigger('click')
    await flushPromises()
    expect(submitFamilyFeedbackMock).toHaveBeenCalledWith('event-mental-week', {
      feedback_type: 'confirm', feedback_kind: 'CARE', value: weeklyMock.care.options[0], operator: 'family',
    })
    expect(wrapper.get('[data-testid="care-submit"]').text()).toContain('关怀反馈已记录')

    wrapper.vm.verifyChoice = weeklyMock.visitor_case.verification_options[2]
    await wrapper.get('[data-testid="verify-submit"]').trigger('click')
    await flushPromises()
    expect(submitFamilyFeedbackMock).toHaveBeenCalledWith('event-fraud-visitor', {
      feedback_type: 'confirm', feedback_kind: 'IDENTITY_VERIFICATION', value: weeklyMock.visitor_case.verification_options[2], operator: 'family',
    })
    expect(wrapper.get('[data-testid="verify-submit"]').text()).toContain('身份核验已记录')
  })

  it('API 缺少周报扩展数据时展示诚实空状态并禁用提交', async () => {
    getWeeklyReportMock.mockResolvedValue({
      resident_id: 'resident-api', period: '2026-08-01 至 2026-08-07', generated_at: '2026-08-07T08:00:00+08:00',
      risk_level: 'GREEN', source_mode: 'RECORDED_REPLAY', simulated: true,
      summary: '后端周报摘要', trend: [], evidence: [], recommendations: [],
      care: { status: 'PENDING', last_contact: null, options: [] }, visitor_case: null,
    })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('当前 API 未提供周报趋势序列')
    expect(wrapper.text()).toContain('当前 API 未提供关怀选项')
    expect(wrapper.text()).toContain('当前 API 未返回 visitor_case，不使用 Mock 访客数据填充')
    expect(wrapper.get('[data-testid="care-submit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="visitor-panel"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="visitor-panel-empty"]').exists()).toBe(true)
  })
})
