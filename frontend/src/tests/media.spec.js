import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MediaPanel from '../components/common/MediaPanel.vue'
import { formatAssetId } from '../utils/format'

describe('授权媒体降级', () => {
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
  })

  it('Observation 没有 asset_id 时显示不可追溯提示', () => {
    expect(formatAssetId(null)).toBe('暂无可追溯视频')
    expect(formatAssetId('asset-001')).toBe('asset-001')
  })
})
