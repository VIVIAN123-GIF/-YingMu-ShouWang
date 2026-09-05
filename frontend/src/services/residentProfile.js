import { reactive } from 'vue'

export const RESIDENT_PROFILE_KEY = 'yingmu-resident-profile-v1'
export const defaultResidentProfile = Object.freeze({
  name: '张建国', age: 60, relation: '母亲', location: '杭州 · 家中', living: '独居',
  mobility: '可独立行走', jointIssues: '膝关节偶有不适', fallHistory: '近一年无跌倒记录', dizziness: '偶尔起夜头晕',
  medication: '晚间服用降压药，家属每周核对', sleep: '22:30 入睡，06:30 起床', assistiveDevice: '卫生间设有扶手',
  noticeLevel: '橙色风险通知家属', emergencyContact: '女儿', privacyZones: '卧室床边、卫生间',
  videoConsent: true, audioConsent: true, reminder: '请先坐稳，再慢慢起身', filledBy: '家属填写',
})

function readProfile() {
  try {
    const storedProfile = JSON.parse(localStorage.getItem(RESIDENT_PROFILE_KEY) || '{}')
    if (storedProfile.age === 76 && storedProfile.relation === '父亲') {
      storedProfile.age = 60
      storedProfile.relation = '母亲'
    }
    return { ...defaultResidentProfile, ...storedProfile }
  }
  catch { return { ...defaultResidentProfile } }
}

export function useResidentProfile() {
  const profile = reactive(readProfile())
  function save() {
    try { localStorage.setItem(RESIDENT_PROFILE_KEY, JSON.stringify({ ...profile, updatedAt: new Date().toISOString() })) } catch { /* offline storage may be unavailable */ }
  }
  function reset() { Object.assign(profile, defaultResidentProfile); save() }
  return { profile, save, reset }
}
