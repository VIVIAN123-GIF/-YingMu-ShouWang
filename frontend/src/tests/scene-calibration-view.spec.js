import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import sceneCalibration from '../replay-data/scene-calibration.json'
import { cameraPositionLabel, sceneConfigLabel, schemaVersionLabel, zoneIdentifierLabel } from '../utils/format'

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
      'el-table': { name: 'ElTable', props: ['data'], emits: ['cell-mouse-enter', 'cell-mouse-leave'], template: '<div class="table-stub">{{ data.length }} rows<slot /></div>' },
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
    expect(wrapper.text()).toContain(schemaVersionLabel(sceneCalibration.schema_version))
    expect(wrapper.text()).toContain(sceneConfigLabel(sceneCalibration.scene_config_id))
    expect(wrapper.text()).toContain(cameraPositionLabel(sceneCalibration.camera_position_id))
    expect(wrapper.text()).not.toContain('recorded-fixed-demo-v1')
    expect(wrapper.findAll('polygon')).toHaveLength(sceneCalibration.zones.length)
    expect(wrapper.text()).toContain('2 rows')
  })

  it('links canvas and table hover states to the matching zone', async () => {
    mocks.getSceneCalibration.mockResolvedValue(structuredClone(sceneCalibration))
    const wrapper = mountView(); await flushPromises()
    await wrapper.findAll('.calibration-zone')[0].trigger('mouseenter', { clientX: 20, clientY: 20 })
    expect(wrapper.find('.calibration-canvas-tooltip').text()).toContain(zoneIdentifierLabel(sceneCalibration.zones[0].zone_id))
    expect(wrapper.findAll('.calibration-zone')[0].classes()).toContain('is-active')

    wrapper.findComponent({ name: 'ElTable' }).vm.$emit('cell-mouse-enter', sceneCalibration.zones[1])
    await nextTick()
    expect(wrapper.findAll('.calibration-zone')[1].classes()).toContain('is-active')
  })

  it('将 C6c 场景和区域内部标识显示为中文', async () => {
    const c6cCalibration = {
      ...structuredClone(sceneCalibration),
      scene_config_id: 'living-room-c6c-20260831',
      camera_position_id: 'living-room-new-position-01',
      zones: [
        { zone_id: 'living-room-activity-safe', zone_type: 'SAFE', polygon_norm: [[0, 0], [1, 0], [1, 1]] },
        { zone_id: 'hallway-doorway-risk', zone_type: 'HIGH_RISK', polygon_norm: [[0, 0], [1, 0], [1, 1]] },
        { zone_id: 'sofa-seating-support', zone_type: 'SUPPORT', polygon_norm: [[0, 0], [1, 0], [1, 1]] },
        { zone_id: 'dining-cabinet-obstacle', zone_type: 'OBSTACLE', polygon_norm: [[0, 0], [1, 0], [1, 1]] },
      ],
    }
    mocks.getSceneCalibration.mockResolvedValue(c6cCalibration)
    const wrapper = mountView(); await flushPromises()

    expect(wrapper.text()).toContain('客厅 C6c 场景配置')
    expect(wrapper.text()).toContain('客厅新机位 01')
    expect(wrapper.text()).toContain('客厅活动安全区')
    expect(wrapper.text()).toContain('走廊门口高风险区')
    expect(wrapper.text()).toContain('沙发坐席支撑区')
    expect(wrapper.text()).toContain('餐边柜障碍区')
    expect(wrapper.text()).not.toContain('living-room-activity-safe')
    expect(wrapper.text()).not.toContain('hallway-doorway-risk')
  })

  it.each([
    ['SCENE_CONFIG_MISSING', '场景标定不存在或尚未安装'],
    ['SCENE_CONFIG_INVALID', '场景标定配置非法'],
  ])('展示 %s 可理解错误状态和请求 ID', async (code, message) => {
    mocks.getSceneCalibration.mockRejectedValue(Object.assign(new Error(code), { api: { code, request_id: 'req-scene-1' } }))
    const wrapper = mountView(); await flushPromises()
    expect(wrapper.text()).toContain(message)
    expect(wrapper.text()).not.toContain(code)
    expect(wrapper.text()).toContain(code === 'SCENE_CONFIG_MISSING' ? '未找到场景标定' : '场景标定无效')
    expect(wrapper.text()).toContain('req-scene-1')
  })
})
