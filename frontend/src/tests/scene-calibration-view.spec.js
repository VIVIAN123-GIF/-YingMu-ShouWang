import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import sceneCalibration from '../replay-data/scene-calibration.json'

const mocks = vi.hoisted(() => ({ getSceneCalibration: vi.fn(), getLatestForewarning: vi.fn(), push: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { sceneConfigId: 'scene-replay-living-room' } }),
  useRouter: () => ({ push: mocks.push }),
}))
vi.mock('../services/repository', () => ({
  getSceneCalibration: mocks.getSceneCalibration, getLatestForewarning: mocks.getLatestForewarning,
  runtime: { activeSource: 'replay_dataset' },
}))

import SceneCalibrationView from '../views/SceneCalibrationView.vue'

function mountView() {
  return mount(SceneCalibrationView, { global: {
    directives: { loading: () => {} },
    stubs: {
      PageHeader: { template: '<header><slot /></header>' }, SourceBadge: { template: '<span class="source-stub" />' },
      'el-button': { template: '<button><slot /></button>' }, 'el-alert': { props: ['title'], template: '<div class="alert-stub">{{ title }}<slot /></div>' },
      'el-tag': { template: '<span><slot /></span>' }, 'el-icon': { template: '<i><slot /></i>' },
      'el-table': { props: ['data'], template: '<div class="table-stub">{{ data.length }} rows<slot /></div>' },
      'el-table-column': { template: '<span />' },
    },
  } })
}

describe('场景标定详情页', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset())
    mocks.getLatestForewarning.mockResolvedValue({ ...sceneCalibration, source_mode: 'RECORDED_REPLAY', simulated: true })
  })

  it('展示配置版本、摄像机位置和区域多边形', async () => {
    mocks.getSceneCalibration.mockResolvedValue(structuredClone(sceneCalibration))
    const wrapper = mountView(); await flushPromises()
    expect(wrapper.text()).toContain('scene-calibration/1.0')
    expect(wrapper.text()).toContain('recorded-fixed-demo-v1')
    expect(wrapper.findAll('polygon')).toHaveLength(sceneCalibration.zones.length)
    expect(wrapper.text()).toContain('2 rows')
  })

  it.each([
    ['SCENE_CONFIG_MISSING', '场景标定不存在或尚未安装'],
    ['SCENE_CONFIG_INVALID', '场景标定配置非法'],
  ])('展示 %s 可理解错误状态和请求 ID', async (code, message) => {
    mocks.getSceneCalibration.mockRejectedValue(Object.assign(new Error(code), { api: { code, request_id: 'req-scene-1' } }))
    const wrapper = mountView(); await flushPromises()
    expect(wrapper.text()).toContain(message)
    expect(wrapper.text()).toContain(code)
    expect(wrapper.text()).toContain('req-scene-1')
  })
})
