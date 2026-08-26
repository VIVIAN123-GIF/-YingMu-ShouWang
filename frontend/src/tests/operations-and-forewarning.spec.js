import { afterEach, describe, expect, it, vi } from 'vitest'
import forewarningReplay from '../replay-data/forewarning.json'
import sceneCalibrationReplay from '../replay-data/scene-calibration.json'
import snapshotReplay from '../replay-data/device-snapshot.json'
import {
  apiClient, auditLog, getDashboard, getDeviceSnapshot, getDeviceStatus, getForewarningHistory, getLatestForewarning,
  getSceneCalibration, setDataMode, stopDeviceCollection,
} from '../services/repository'
import { DataContractError, validateDeviceSnapshot, validateSceneCalibration } from '../domain/validation'

const liveDevice = {
  online: true, adapter_mode: 'EZVIZ_CLOUD', source_mode: 'LIVE_DEVICE',
  device_alias: 'camera-live-001', simulated: false, collection_active: true,
}

describe('设备与居民展示接口', () => {
  afterEach(() => { vi.restoreAllMocks(); setDataMode('auto'); auditLog.splice(0) })

  it('读取浏览器安全快照且拒绝临时图片地址', async () => {
    setDataMode('api')
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: structuredClone(snapshotReplay) })
    await expect(getDeviceSnapshot()).resolves.toEqual(snapshotReplay)
    expect(get).toHaveBeenCalledWith('/device/snapshot')
    expect(() => validateDeviceSnapshot({ ...snapshotReplay, temporary_url: 'https://private.example/snapshot.jpg' }))
      .toThrow(DataContractError)
  })

  it('停止采集只向已确认实时设备发送逐次控制令牌', async () => {
    setDataMode('api')
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: liveDevice })
    await getDeviceStatus()
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { ...liveDevice, online: null, collection_active: false } })
    await expect(stopDeviceCollection('one-use-secret')).resolves.toMatchObject({ collection_active: false })
    expect(post).toHaveBeenCalledWith('/device/stop', null, { headers: { 'X-Control-Token': 'one-use-secret' } })
    expect(JSON.stringify(auditLog)).not.toContain('one-use-secret')
    expect(JSON.stringify(sessionStorage)).not.toContain('one-use-secret')
  })

  it('回放设备控制被阻止且不会调用后端', async () => {
    setDataMode('replay')
    await getDeviceStatus()
    const post = vi.spyOn(apiClient, 'post')
    await expect(stopDeviceCollection('token')).rejects.toMatchObject({ api: { code: 'LIVE_CONTROL_UNAVAILABLE' } })
    expect(post).not.toHaveBeenCalled()
  })

  it('按编码后的配置标识读取场景标定', async () => {
    setDataMode('api')
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: structuredClone(sceneCalibrationReplay) })
    await expect(getSceneCalibration('scene api/1')).resolves.toEqual(sceneCalibrationReplay)
    expect(get).toHaveBeenCalledWith('/scene-calibrations/scene%20api%2F1')
  })

  it('场景缺失错误在自动模式下不被回放掩盖', async () => {
    setDataMode('auto')
    const missing = Object.assign(new Error('missing'), { response: { status: 404 }, api: { code: 'SCENE_CONFIG_MISSING', message: 'missing', request_id: 'req-scene' } })
    vi.spyOn(apiClient, 'get').mockRejectedValue(missing)
    await expect(getSceneCalibration('scene-missing')).rejects.toBe(missing)
  })

  it('最新预警允许为空，历史查询保留时区参数和上限', async () => {
    setDataMode('api')
    const get = vi.spyOn(apiClient, 'get')
      .mockResolvedValueOnce({ data: null })
      .mockResolvedValueOnce({ data: [structuredClone(forewarningReplay[0])] })
    await expect(getLatestForewarning('resident api/1')).resolves.toBeNull()
    await expect(getForewarningHistory('resident api/1', {
      from: '2026-08-01T00:00:00+08:00', to: '2026-08-26T23:59:59+08:00', limit: 999,
    })).resolves.toHaveLength(1)
    expect(get).toHaveBeenNthCalledWith(1, '/residents/resident%20api%2F1/forewarning/latest')
    expect(get).toHaveBeenNthCalledWith(2, '/residents/resident%20api%2F1/forewarning', { params: {
      from: '2026-08-01T00:00:00+08:00', to: '2026-08-26T23:59:59+08:00', limit: 500,
    } })
  })

  it('回放模式可同时读取居民档案、最新预警和历史', async () => {
    setDataMode('replay')
    const [dashboard, latest, history] = await Promise.all([
      getDashboard(), getLatestForewarning(), getForewarningHistory(),
    ])
    expect(dashboard.today.care_status).toBeTruthy()
    expect(latest?.snapshot_id).toBeTruthy()
    expect(history).toHaveLength(forewarningReplay.length)
  })

  it('非法场景多边形触发数据契约错误', () => {
    const invalid = structuredClone(sceneCalibrationReplay)
    invalid.zones[0].polygon_norm = [[0, 0], [0.5, 0.5], [1, 1]]
    expect(() => validateSceneCalibration(invalid)).toThrow(DataContractError)
  })
})
