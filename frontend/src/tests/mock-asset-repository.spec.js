import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('Mock 授权视频素材', () => {
  beforeEach(() => {
    vi.resetModules()
    sessionStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  async function loadRepository(clipUrl = '') {
    vi.stubEnv('VITE_DATA_MODE', 'replay')
    vi.stubEnv('VITE_AUTHORIZED_CLIP_URL', clipUrl)
    return import('../services/repository')
  }

  it('为关联素材接入已配置的本地授权视频', async () => {
    const { getAsset } = await loadRepository('/media/authorized-fall-clip.mp4')

    const asset = await getAsset('asset-fall-authorized')

    expect(asset).toMatchObject({
      asset_id: 'asset-fall-authorized',
      source_mode: 'RECORDED_REPLAY',
      simulated: true,
      fallback_url: '/media/authorized-fall-clip.mp4',
      available: true,
      verification_status: 'AUTHORIZED_LOCAL_CLIP',
    })
  })

  it('未配置覆盖地址时使用固定 JSON 中的跌倒风险片段', async () => {
    const { getAsset } = await loadRepository()

    const asset = await getAsset('asset-fall-authorized')

    expect(asset).toMatchObject({
      fallback_url: '/media/fall-risk-replay.mp4',
      available: true,
      verification_status: 'AUTHORIZED_LOCAL_CLIP',
    })
  })

  it('为活动轨迹和日常基线返回各自的回放片段', async () => {
    const { getAsset } = await loadRepository()

    const [activity, daily] = await Promise.all([
      getAsset('asset-mental-week'),
      getAsset('asset-green-daily'),
    ])

    expect(activity.fallback_url).toBe('/media/activity-route-replay-browser.mp4')
    expect(daily.fallback_url).toBe('/media/daily-baseline-replay-browser.mp4')
    expect(activity.fallback_url).not.toBe(daily.fallback_url)
    expect(activity.source_mode).toBe('RECORDED_REPLAY')
    expect(daily.source_mode).toBe('RECORDED_REPLAY')
  })

  it('不为其他素材标识复用授权视频', async () => {
    const { getAsset } = await loadRepository('/media/authorized-fall-clip.mp4')

    const asset = await getAsset('asset-unrelated')

    expect(asset).toMatchObject({
      asset_id: 'asset-unrelated',
      source_mode: 'RECORDED_REPLAY',
      fallback_url: null,
      available: false,
    })
  })

  it('自动模式遇到资产接口500时切换到对应授权回放', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'auto')
    const { apiClient, getAsset, runtime } = await import('../services/repository')
    vi.spyOn(apiClient, 'get').mockRejectedValue({ response: { status: 500 }, message: 'server error' })
    const asset = await getAsset('asset-green-daily')
    expect(asset.fallback_url).toBe('/media/daily-baseline-replay-browser.mp4')
    expect(asset.source_mode).toBe('RECORDED_REPLAY')
    expect(runtime.activeSource).toBe('replay_dataset')
  })

  it('启动时授权素材清单包含三个页面映射', async () => {
    const { validateReplayAssetManifest } = await loadRepository()
    expect(validateReplayAssetManifest()).toEqual([])
  })
})
