import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
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

import CareView from '../views/CareView.vue'

function mountView() {
  return mount(CareView, {
    global: {
      directives: { loading: () => {} },
      stubs: {
        PageHeader: { template: '<header><slot /></header>' },
        RiskBadge: { template: '<span />' },
        SourceBadge: { template: '<span />' },
        'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
        'el-button': { props: ['disabled'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
        'el-radio-group': { props: ['disabled'], template: '<div class="radio-group" :data-disabled="disabled"><slot /></div>' },
        'el-radio': { props: ['value'], emits: ['click'], template: '<label @click="$emit(\'click\')"><input type="radio" :value="value" /><slot /></label>' },
      },
    },
  })
}

describe('关怀结果修正', () => {
  beforeEach(() => {
    getWeeklyReportMock.mockReset()
    submitFamilyFeedbackMock.mockReset()
    Object.values(messageMock).forEach((mock) => mock.mockReset())
  })

  it('已有记录时选项仍可用，并可提交新的联系结果', async () => {
    const report = structuredClone(weeklyMock)
    report.care.status = 'SUBMITTED'
    report.care.feedback_record = {
      value: report.care.options[0], recorded_at: '2026-09-02T09:00:00+08:00', operator: 'family',
    }
    getWeeklyReportMock.mockResolvedValue(report)
    submitFamilyFeedbackMock.mockResolvedValue({
      value: report.care.options[1], recorded_at: '2026-09-02T10:00:00+08:00', operator: 'family',
    })
    const wrapper = mountView(); await flushPromises()

    expect(wrapper.vm.choice).toBe(report.care.options[0])
    expect(wrapper.get('.radio-group').attributes('data-disabled')).toBeUndefined()
    expect(wrapper.get('[data-testid="care-workbench"] button').attributes('disabled')).toBeUndefined()

    await wrapper.findAll('.radio-group label')[1].trigger('click')
    await nextTick()
    expect(wrapper.vm.choice).toBe(report.care.options[1])
    await wrapper.get('[data-testid="care-workbench"] button').trigger('click')
    await flushPromises()

    expect(submitFamilyFeedbackMock).toHaveBeenCalledWith('event-mental-week', {
      feedback_type: 'confirm', feedback_kind: 'CARE', value: report.care.options[1], operator: 'family',
    })
    expect(wrapper.get('[data-testid="care-workbench"] button').text()).toContain('更新关怀反馈')
  })
})
