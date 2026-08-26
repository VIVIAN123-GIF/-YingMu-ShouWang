import { computed, reactive } from 'vue'

export const VIEW_MODES = Object.freeze({ family: '家属视图', review: '评审视图' })
export const VIEW_MODE_STORAGE_KEY = 'yingmu-view-mode'

function storedMode() {
  try {
    const value = localStorage.getItem(VIEW_MODE_STORAGE_KEY)
    return Object.hasOwn(VIEW_MODES, value) ? value : 'family'
  } catch { return 'family' }
}

export const viewModeState = reactive({ mode: storedMode() })

export function setViewMode(mode) {
  if (!Object.hasOwn(VIEW_MODES, mode)) return
  viewModeState.mode = mode
  try { localStorage.setItem(VIEW_MODE_STORAGE_KEY, mode) } catch { /* Storage may be unavailable. */ }
}

export function useViewMode() {
  return {
    mode: computed(() => viewModeState.mode),
    isFamily: computed(() => viewModeState.mode === 'family'),
    isReview: computed(() => viewModeState.mode === 'review'),
    setViewMode,
  }
}
