import { describe, expect, it } from 'vitest'
import selectedMedia from '../replay-data/selected-media.json'
import { getSelectedEventMedia } from '../services/repository'

describe('精选受控视频映射', () => {
  it('保留 31 条脱敏的本地精选素材，且全部标记为回放模拟数据', () => {
    expect(selectedMedia).toHaveLength(31)
    for (const clip of selectedMedia) {
      expect(clip.file).toMatch(/^[a-z0-9-]+\.mp4$/)
      expect(clip.participant_id).toBeTruthy()
      expect(clip.sha256_short).toMatch(/^[a-f0-9]{11,12}$/)
      expect(clip.asset_id).toMatch(/^selected-/)
    }
  })

  it('仅向显式映射的模拟回放事件提供工程对照，真实设备与无关领域不替换媒体', () => {
    const selected = getSelectedEventMedia({ event_id: 'event-fall-intervening', source_mode: 'RECORDED_REPLAY', simulated: true })
    expect(selected.primary_asset_id).toBe('selected-new-risk-left-take03')
    expect(selected.entries.every((clip) => clip.source_mode === 'RECORDED_REPLAY' && clip.simulated === true)).toBe(true)
    expect(getSelectedEventMedia({ event_id: 'event-fi-resident-001-run-01-event-green-daily', source_mode: 'RECORDED_REPLAY', simulated: true })?.primary_asset_id)
      .toBe('selected-new-normal-control-take02')
    expect(getSelectedEventMedia({ event_id: 'event-mental-week', source_mode: 'RECORDED_REPLAY', simulated: true })).toBeNull()
    expect(getSelectedEventMedia({ event_id: 'event-fall-intervening', source_mode: 'LIVE_DEVICE', simulated: false })).toBeNull()
  })
})
