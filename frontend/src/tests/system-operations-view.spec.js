import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getDeviceStatus: vi.fn(), getLatestForewarning: vi.fn(), getCurrentSceneCalibration: vi.fn(), getDeviceSnapshot: vi.fn(), createDeviceSnapshot: vi.fn(),
  stopDeviceCollection: vi.fn(), getFeedbackAuditRecords: vi.fn(), clearRecordedFeedback: vi.fn(), push: vi.fn(),
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
vi.mock('../services/repository', () => ({
  clearRecordedFeedback: mocks.clearRecordedFeedback, getFeedbackAuditRecords: mocks.getFeedbackAuditRecords,
  getDeviceStatus: mocks.getDeviceStatus, getLatestForewarning: mocks.getLatestForewarning, getCurrentSceneCalibration: mocks.getCurrentSceneCalibration,
  getDeviceSnapshot: mocks.getDeviceSnapshot, createDeviceSnapshot: mocks.createDeviceSnapshot, stopDeviceCollection: mocks.stopDeviceCollection,
  runtime: { mode: 'api', activeSource: 'api' },
}))

import SystemView from '../views/SystemView.vue'

const device = { online: true, adapter_mode: 'EZVIZ_CLOUD', source_mode: 'LIVE_DEVICE', device_alias: 'camera-live', simulated: false, collection_active: true }
const latest = { scene_config_id: 'scene-live', evaluated_at: '2026-08-26T19:00:00+08:00', source_mode: 'LIVE_DEVICE', simulated: false }
const snapshot = { request_id: 'snapshot-1', device_ref: 'device-live', channel_no: 1, captured_at: '2026-08-26T19:00:00+08:00', provider_latency_ms: 12, source_mode: 'LIVE_DEVICE', simulated: false }

function mountView() {
  return mount(SystemView, { global: {
    directives: { loading: () => {} },
    stubs: {
      PageHeader: { template: '<header><slot /></header>' }, SourceBadge: { template: '<span class="source-stub" />' },
      TechnicalDisclosure: { template: '<div class="technical-stub"><slot /></div>' },
      LiveVideoPanel: { props: ['available', 'autoStart'], template: '<section data-testid="device-live" :data-auto-start="autoStart">摄像头直播</section>' },
      'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
      'el-alert': { props: ['title'], template: '<div class="alert-stub">{{ title }}<slot /></div>' },
      'el-empty': { props: ['description'], template: '<div class="empty-stub">{{ description }}</div>' },
      'el-dialog': { template: '<div class="dialog-stub"><slot /><slot name="footer" /></div>' },
      'el-form': { template: '<form><slot /></form>' }, 'el-form-item': { template: '<label><slot /></label>' },
      'el-input': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
      'el-tag': { template: '<span><slot /></span>' }, 'el-icon': { template: '<i><slot /></i>' },
    },
  } })
}

describe('系统设备运维页面', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset())
    mocks.getDeviceStatus.mockResolvedValue(structuredClone(device))
    mocks.getLatestForewarning.mockResolvedValue(structuredClone(latest))
    mocks.getCurrentSceneCalibration.mockRejectedValue(new Error('not configured'))
    mocks.getDeviceSnapshot.mockResolvedValue(structuredClone(snapshot))
    mocks.createDeviceSnapshot.mockResolvedValue(structuredClone(snapshot))
    mocks.getFeedbackAuditRecords.mockResolvedValue([])
  })
  afterEach(() => { vi.useRealTimers() })

  it('每 2000ms 刷新设备与最新预警，并在卸载后停止', async () => {
    vi.useFakeTimers()
    const wrapper = mountView(); await flushPromises()
    expect(mocks.getDeviceStatus).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(mocks.getDeviceStatus).toHaveBeenCalledTimes(2)
    expect(mocks.getLatestForewarning).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(4000)
    expect(mocks.getDeviceStatus).toHaveBeenCalledTimes(2)
  })
  it('统一视图常驻显示停止采集入口，实时来源允许操作', async () => {
    const wrapper = mountView(); await flushPromises()
    expect(wrapper.find('[data-testid="stop-collection"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="stop-collection"]').attributes('disabled')).toBeUndefined()
  })

  it('回放来源保留停止采集入口但禁止操作', async () => {
    mocks.getDeviceStatus.mockResolvedValue({ ...device, source_mode: 'RECORDED_REPLAY', simulated: true })
    const wrapper = mountView(); await flushPromises()
    expect(wrapper.get('[data-testid="stop-collection"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('回放或降级来源不能执行设备控制')
  })

  it('进入页面自动获取快照并允许手动再次抓拍', async () => {
    const wrapper = mountView(); await flushPromises()
    await wrapper.get('.snapshot-card button').trigger('click'); await flushPromises()
    expect(mocks.createDeviceSnapshot).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('抓拍已完成')
    expect(wrapper.text()).not.toContain('图片通过受控媒体会话加载')
  })

  it('首次主动抓拍完成前显示稳定的处理中状态', async () => {
    let resolveSnapshot
    mocks.createDeviceSnapshot.mockImplementationOnce(() => new Promise((resolve) => { resolveSnapshot = resolve }))
    const wrapper = mountView(); await flushPromises()

    expect(wrapper.get('.snapshot-card').classes()).toContain('snapshot-card-pending')
    expect(wrapper.text()).toContain('正在获取主动抓拍')
    expect(wrapper.text()).not.toContain('等待首次快照记录')

    resolveSnapshot(structuredClone(snapshot))
    await flushPromises()
    expect(wrapper.get('.snapshot-card').classes()).not.toContain('snapshot-card-pending')
    expect(wrapper.text()).toContain('抓拍已完成')
  })

  it('在当前设备卡片下方渲染摄像头直播入口', async () => {
    const wrapper = mountView(); await flushPromises()
    expect(wrapper.find('[data-testid="device-live"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('摄像头直播')
  })

  it('停止失败展示后端错误码和请求 ID并清空令牌', async () => {
    mocks.stopDeviceCollection.mockRejectedValue(Object.assign(new Error('forbidden'), {
      api: { code: 'CONTROL_FORBIDDEN', message: '无权停止采集', request_id: 'req-control-1' },
    }))
    const wrapper = mountView(); await flushPromises()
    await wrapper.get('[data-testid="control-token"]').setValue('secret-once')
    const confirm = wrapper.findAll('button').find((button) => button.text().includes('确认停止'))
    await confirm.trigger('click'); await flushPromises()
    expect(mocks.stopDeviceCollection).toHaveBeenCalledWith('secret-once')
    expect(wrapper.text()).toContain('没有设备控制权限')
    expect(wrapper.text()).not.toContain('CONTROL_FORBIDDEN')
    expect(wrapper.text()).toContain('req-control-1')
    expect(wrapper.get('[data-testid="control-token"]').element.value).toBe('')
  })

  it('桌面端右侧卡片保留内容所需高度，避免压到下方区域', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/styles/main.css'), 'utf8')
    expect(css).toContain('.system-side-stack { align-self: stretch; width: 100%; }')
    expect(css).toContain('.system-side-stack > .adapter-mode-card { flex: 1 0 auto; }')
    expect(css).not.toContain('.snapshot-card-empty { align-self: start; min-height: 0 !important; }')
  })

  it('打开或取消清除确认时保留当前记录', async () => {
    mocks.getFeedbackAuditRecords.mockResolvedValue([
      { feedback_id: 'feedback-local', event_id: 'event-local', feedback_kind: 'CARE', value: '已联系', recorded_at: '2026-09-02T09:00:00+08:00', saved_in_demo: true },
      { feedback_id: 'feedback-db', event_id: 'event-db', feedback_kind: 'IDENTITY_VERIFICATION', value: '身份已确认', recorded_at: '2026-09-02T10:00:00+08:00', saved_in_demo: false },
    ])
    const wrapper = mountView(); await flushPromises()

    expect(wrapper.findAll('.recorded-feedback')).toHaveLength(2)
    await wrapper.get('[data-testid="clear-feedback"]').trigger('click')
    await flushPromises()

    expect(mocks.clearRecordedFeedback).not.toHaveBeenCalled()
    expect(wrapper.findAll('.recorded-feedback')).toHaveLength(2)
    expect(wrapper.text()).toContain('确认清除本页显示的反馈记录吗？')

    await wrapper.get('[data-testid="clear-feedback-cancel"]').trigger('click')
    expect(mocks.clearRecordedFeedback).not.toHaveBeenCalled()
    expect(wrapper.findAll('.recorded-feedback')).toHaveLength(2)
  })

  it('确认清除后才清空当前列表，并说明数据库审计记录仍保留', async () => {
    mocks.getFeedbackAuditRecords.mockResolvedValue([
      { feedback_id: 'feedback-local', event_id: 'event-local', feedback_kind: 'CARE', value: '已联系', recorded_at: '2026-09-02T09:00:00+08:00', saved_in_demo: true },
      { feedback_id: 'feedback-db', event_id: 'event-db', feedback_kind: 'IDENTITY_VERIFICATION', value: '身份已确认', recorded_at: '2026-09-02T10:00:00+08:00', saved_in_demo: false },
    ])
    const wrapper = mountView(); await flushPromises()

    await wrapper.get('[data-testid="clear-feedback"]').trigger('click')
    await wrapper.get('[data-testid="clear-feedback-confirm"]').trigger('click')
    await flushPromises()

    expect(mocks.clearRecordedFeedback).toHaveBeenCalledOnce()
    expect(wrapper.findAll('.recorded-feedback')).toHaveLength(0)
    expect(wrapper.text()).toContain('尚未记录关怀反馈或身份核验')
    expect(wrapper.get('[data-testid="feedback-clear-notice"]').text()).toContain('数据库审计记录未删除')
  })
})
