import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MediaPanel from '../components/common/MediaPanel.vue'
import { formatAssetId } from '../utils/format'

describe('授权媒体降级', () => {
  it('将模拟媒体的英文标题显示为中文', () => {
    const wrapper = mount(MediaPanel, {
      props: { asset: { title: 'Simulated unavailable media (asset-fall-authorized)' } },
    })
    expect(wrapper.text()).toContain('模拟媒体暂不可用')
    expect(wrapper.text()).not.toContain('Simulated unavailable media')
  })

  it('没有授权文件时明确显示待核验且不伪装实时画面', () => {
    const wrapper = mount(MediaPanel, {
      props: {
        asset: {
          title: '授权片段', source_mode: 'RECORDED_REPLAY', simulated: true,
          stream_url: null, fallback_url: null, notice: '当前尚未提供视频文件',
        },
      },
    })
    expect(wrapper.text()).toContain('待素材核验')
    expect(wrapper.text()).toContain('不伪装为实时视频')
    expect(wrapper.find('video').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.get('.media-placeholder-status').attributes('role')).toBe('status')
  })

  it('授权文件地址有效时渲染视频播放器', () => {
    const wrapper = mount(MediaPanel, {
      props: {
        asset: {
          title: '授权片段', source_mode: 'RECORDED_REPLAY', simulated: true,
          stream_url: null, fallback_url: '/media/authorized-fall-clip.mp4', notice: '已配置授权片段',
        },
      },
    })

    expect(wrapper.get('video').attributes('src')).toBe('/media/authorized-fall-clip.mp4')
    expect(wrapper.get('video').element.autoplay).toBe(true)
    expect(wrapper.get('video').element.muted).toBe(true)
  })

  it('授权回放加载完成后自动静音播放，真实设备媒体不强制自动播放', async () => {
    const replayWrapper = mount(MediaPanel, {
      props: {
        asset: {
          title: '授权回放', source_mode: 'RECORDED_REPLAY', simulated: true,
          stream_url: null, fallback_url: '/media/authorized-replay.mp4',
        },
      },
    })
    const replayVideo = replayWrapper.get('video')
    await replayVideo.trigger('loadeddata')

    expect(replayVideo.element.autoplay).toBe(true)
    expect(replayVideo.element.muted).toBe(true)

    const liveWrapper = mount(MediaPanel, {
      props: {
        asset: {
          title: '真实设备录像', source_mode: 'LIVE_DEVICE', simulated: false,
          stream_url: '/media/assets/live-private', fallback_url: null,
        },
        sourceMode: 'LIVE_DEVICE',
        simulated: false,
      },
    })

    expect(liveWrapper.get('video').element.autoplay).toBe(false)
    expect(liveWrapper.get('video').element.muted).toBe(false)
  })

  it('加载元数据后使用视频原始宽高比，不强制16:9', async () => {
    const wrapper = mount(MediaPanel, {
      props: { asset: { title: '竖屏片段', source_mode: 'RECORDED_REPLAY', simulated: true, stream_url: null, fallback_url: '/media/daily-baseline-replay.mp4' } },
    })
    const video = wrapper.get('video')
    Object.defineProperty(video.element, 'videoWidth', { value: 720, configurable: true })
    Object.defineProperty(video.element, 'videoHeight', { value: 1280, configurable: true })
    Object.defineProperty(video.element, 'duration', { value: 20, configurable: true })
    await video.trigger('loadedmetadata')
    await video.trigger('loadeddata')
    expect(wrapper.get('.media-video-frame').attributes('data-aspect-ratio')).toBe('720 / 1280')
    expect(video.element.style.aspectRatio).toBe('720 / 1280')
    expect(wrapper.text()).toContain('授权片段已加载')
  })

  it('stream_url 解码失败时只回退到同一资产的本地地址', async () => {
    const wrapper = mount(MediaPanel, {
      props: { asset: { title: '直播优先片段', source_mode: 'RECORDED_REPLAY', simulated: true, stream_url: '/stream/asset.mp4', fallback_url: '/media/daily-baseline-replay.mp4' } },
    })
    await wrapper.get('video').trigger('error')
    expect(wrapper.get('video').attributes('src')).toBe('/media/daily-baseline-replay.mp4')
    await wrapper.get('video').trigger('error')
    expect(wrapper.find('video').exists()).toBe(false)
  })

  it('授权文件加载失败时移除播放器并显示失败提示', async () => {
    const wrapper = mount(MediaPanel, {
      props: {
        asset: {
          title: '授权片段', source_mode: 'RECORDED_REPLAY', simulated: true,
          stream_url: null, fallback_url: '/media/missing.mp4', notice: '已配置授权片段',
        },
      },
    })

    await wrapper.get('video').trigger('error')

    expect(wrapper.find('video').exists()).toBe(false)
    expect(wrapper.text()).toContain('授权片段加载失败')
  })

  it('Observation 没有 asset_id 时显示不可追溯提示', () => {
    expect(formatAssetId(null)).toBe('暂无可追溯视频')
    expect(formatAssetId('asset-001')).toBe('受控素材 001')
  })
})
