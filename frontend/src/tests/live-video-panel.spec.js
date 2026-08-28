import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  isSupported: vi.fn(),
  createPlayer: vi.fn(),
  player: null,
  errorHandler: null,
}))

vi.mock('flv.js', () => ({
  default: {
    Events: { ERROR: 'error' },
    isSupported: mocks.isSupported,
    createPlayer: mocks.createPlayer,
  },
}))

import LiveVideoPanel from '../components/common/LiveVideoPanel.vue'

function makePlayer() {
  return {
    attachMediaElement: vi.fn(),
    detachMediaElement: vi.fn(),
    load: vi.fn(),
    play: vi.fn().mockResolvedValue(undefined),
    pause: vi.fn(),
    unload: vi.fn(),
    destroy: vi.fn(),
    on: vi.fn((event, handler) => {
      if (event === 'error') mocks.errorHandler = handler
    }),
  }
}

function mountPanel(available = true, autoStart = false) {
  return mount(LiveVideoPanel, {
    props: { available, autoStart },
    global: {
      stubs: {
        'el-button': {
          props: ['disabled'],
          emits: ['click'],
          template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
        },
        'el-icon': { template: '<i><slot /></i>' },
      },
    },
  })
}

describe('摄像头直播面板', () => {
  beforeEach(() => {
    mocks.errorHandler = null
    mocks.isSupported.mockReset().mockReturnValue(true)
    mocks.player = makePlayer()
    mocks.createPlayer.mockReset().mockReturnValue(mocks.player)
  })

  it('通过同源媒体 BFF 创建带 Cookie 的 HTTP-FLV 播放器', async () => {
    const wrapper = mountPanel()
    expect(wrapper.get('video').attributes('controls')).toBeUndefined()
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(mocks.createPlayer).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'flv', isLive: true, url: '/media/live', withCredentials: true }),
      expect.objectContaining({ enableStashBuffer: false, lazyLoad: false }),
    )
    expect(mocks.player.attachMediaElement).toHaveBeenCalledWith(wrapper.get('video').element)
    expect(mocks.player.load).toHaveBeenCalledTimes(1)
    expect(mocks.player.play).toHaveBeenCalledTimes(1)
  })

  it('进入页面后自动启动直播', async () => {
    mountPanel(true, true)
    await flushPromises()
    expect(mocks.createPlayer).toHaveBeenCalledTimes(1)
  })

  it('停止直播时完整销毁播放器', async () => {
    const wrapper = mountPanel()
    await wrapper.get('button').trigger('click')
    await flushPromises()
    await wrapper.get('button').trigger('click')

    expect(mocks.player.pause).toHaveBeenCalledTimes(1)
    expect(mocks.player.unload).toHaveBeenCalledTimes(1)
    expect(mocks.player.detachMediaElement).toHaveBeenCalledTimes(1)
    expect(mocks.player.destroy).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('直播尚未开始')
  })

  it('播放器断流后显示可重试的失败状态', async () => {
    const wrapper = mountPanel()
    await wrapper.get('button').trigger('click')
    await flushPromises()
    mocks.errorHandler()
    await flushPromises()

    expect(mocks.player.destroy).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('直播暂不可用')
    expect(wrapper.text()).toContain('直播连接已中断')
  })

  it('设备不可用或浏览器不支持时不发起直播请求', async () => {
    const unavailable = mountPanel(false)
    expect(unavailable.get('button').attributes('disabled')).toBeDefined()
    await unavailable.get('button').trigger('click')
    expect(mocks.createPlayer).not.toHaveBeenCalled()
    unavailable.unmount()

    mocks.isSupported.mockReturnValue(false)
    const unsupported = mountPanel()
    await unsupported.get('button').trigger('click')
    expect(mocks.createPlayer).not.toHaveBeenCalled()
    expect(unsupported.text()).toContain('当前浏览器不支持 HTTP-FLV')
  })
})
