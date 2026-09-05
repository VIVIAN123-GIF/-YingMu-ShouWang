<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatLineRound, Clock, Connection, DataAnalysis, House, InfoFilled, Menu, Monitor, TrendCharts, User, VideoPlay, Warning } from '@element-plus/icons-vue'
import { routes } from '../../router'
import { getEvents, runtime } from '../../services/repository'

const route = useRoute()
const router = useRouter()
const collapsed = ref(true)
const mobileNavigationOpen = ref(false)
const openingEventDetail = ref(false)
const runtimeBannerVisible = ref(false)
let runtimeBannerTimer
const pagesBuild = import.meta.env.VITE_PAGES_BUILD === 'true'
const iconMap = { ChatLineRound, Clock, DataAnalysis, House, Monitor, TrendCharts, User, VideoPlay }
const groupConfig = [
  { label: '总览', paths: ['/'] },
  { label: '风险处置', paths: ['/events', '/replay'] },
  { label: '关怀趋势', paths: ['/baseline', '/care', '/weekly'] },
  { label: '系统与材料', paths: ['/resident', '/system'] },
]
const navRoutes = routes.filter((item) => item.meta?.nav)
const navGroups = groupConfig.map((group) => ({ ...group, items: group.paths.map((path) => navRoutes.find((item) => item.path === path)).filter(Boolean) }))
const dataModeLabel = computed(() => {
  if (pagesBuild || runtime.mode === 'replay') return '授权回放'
  if (runtime.mode === 'api') return '实时连接'
  return '融合视图'
})
const activePath = computed(() => ['event-detail', 'event-detail-empty'].includes(route.name) ? '/events' : route.path)
const currentPage = computed(() => ({
  title: route.meta?.title || '统一家属端',
  group: groupConfig.find((group) => group.paths.includes(activePath.value))?.label || '萤目守望',
}))

function createdAtTimestamp(event) { const timestamp = Date.parse(event?.created_at || ''); return Number.isNaN(timestamp) ? 0 : timestamp }
function expandSidebar() { collapsed.value = false }
function collapseSidebar() { collapsed.value = true }
function handleSidebarFocusOut(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) collapseSidebar()
}
function hideRuntimeBanner() {
  runtimeBannerVisible.value = false
  runtimeBannerTimer = undefined
}
function handleTopWheel(event) {
  if (window.scrollY > 1 || event.deltaY >= 0 || !runtime.message) return
  runtimeBannerVisible.value = true
  clearTimeout(runtimeBannerTimer)
  runtimeBannerTimer = window.setTimeout(hideRuntimeBanner, 550)
}

onMounted(() => window.addEventListener('wheel', handleTopWheel, { passive: true }))
onBeforeUnmount(() => {
  window.removeEventListener('wheel', handleTopWheel)
  clearTimeout(runtimeBannerTimer)
})

async function handleSelect(path) {
  mobileNavigationOpen.value = false
  if (path !== '/events/:eventId') { await router.push(path); return }
  if ((route.name === 'event-detail' && route.params.eventId) || openingEventDetail.value) return
  openingEventDetail.value = true
  try {
    const events = await getEvents()
    const liveEvents = events.filter((event) => event.source_mode === 'LIVE_DEVICE' && event.simulated === false)
    const candidates = liveEvents.length ? liveEvents : events
    const latestEvent = candidates.reduce((latest, event) => (!latest || createdAtTimestamp(event) > createdAtTimestamp(latest) ? event : latest), null)
    if (!latestEvent) {
      ElMessage.error('风险事件调取失败：当前居民暂无可用事件')
      await router.push({ name: 'event-detail-empty', query: { reason: 'empty' } })
      return
    }
    await router.push({ name: 'event-detail', params: { eventId: latestEvent.event_id } })
  } catch {
    ElMessage.error('风险事件加载失败，请检查网络后重试')
    await router.push({ name: 'event-detail-empty', query: { reason: 'unavailable' } })
  } finally { openingEventDetail.value = false }
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ collapsed }" @mouseenter="expandSidebar" @mouseleave="collapseSidebar" @focusin="expandSidebar" @focusout="handleSidebarFocusOut">
      <div class="brand"><div class="brand-mark" aria-hidden="true">萤</div><div v-show="!collapsed" class="brand-copy"><strong>萤目守望</strong><span>家庭安全控制台</span></div></div>
      <nav class="navigation navigation-groups" aria-label="主导航">
        <section v-for="group in navGroups" :key="group.label" class="navigation-group">
          <span v-show="!collapsed" class="navigation-label">{{ group.label }}</span>
          <button v-for="item in group.items" :key="item.path" type="button" class="navigation-item" :class="{ active: activePath === item.path }" :aria-current="activePath === item.path ? 'page' : undefined" @click="handleSelect(item.path)">
            <el-icon><component :is="iconMap[item.meta.icon]" /></el-icon><span v-show="!collapsed">{{ item.meta.title }}</span>
          </button>
        </section>
      </nav>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <button class="mobile-menu-button" type="button" aria-label="打开导航" @click="mobileNavigationOpen = true"><el-icon><Menu /></el-icon></button>
        <div class="topbar-context">
          <div class="page-context"><span>{{ currentPage.group }}</span><strong>{{ currentPage.title }}</strong></div>
          <div class="context-divider" aria-hidden="true"></div>
          <div class="resident-identity"><el-avatar :size="36" class="resident-avatar">张</el-avatar><div><strong>张建国</strong><span>60岁 · 杭州家中</span></div></div>
        </div>
        <div class="topbar-actions">
          <div class="data-source-chip" role="status" aria-label="当前数据视图">
            <el-icon><Connection /></el-icon><span>{{ dataModeLabel }}</span>
          </div>
          <div v-if="runtime.degraded" class="degraded-chip" role="status"><el-icon><Warning /></el-icon>服务降级</div>
        </div>
      </header>
      <Transition name="runtime-peek">
        <div v-if="runtime.message && runtimeBannerVisible" class="runtime-banner transient-runtime-banner" :class="{ degraded: runtime.degraded }" role="status"><el-icon><InfoFilled /></el-icon><span>{{ runtime.message }}</span><small v-if="runtime.activeSource === 'replay_dataset'">授权回放</small><small v-else-if="runtime.activeSource === 'combined'">融合数据</small></div>
      </Transition>
      <main
        v-loading="openingEventDetail"
        element-loading-text="正在调取风险事件"
        class="main-content"
        data-testid="event-navigation-loading"
      ><router-view :key="route.fullPath" /></main>
    </div>

    <el-drawer v-model="mobileNavigationOpen" title="萤目守望" direction="ltr" size="min(86vw, 340px)" class="mobile-navigation-drawer">
      <nav class="mobile-navigation" aria-label="移动端主导航">
        <section v-for="group in navGroups" :key="group.label"><span>{{ group.label }}</span>
          <button v-for="item in group.items" :key="item.path" type="button" :class="{ active: activePath === item.path }" @click="handleSelect(item.path)"><el-icon><component :is="iconMap[item.meta.icon]" /></el-icon>{{ item.meta.title }}</button>
        </section>
      </nav>
    </el-drawer>
  </div>
</template>
