<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatLineRound, CircleCheck, Clock, DataAnalysis, DocumentChecked, House, InfoFilled, Menu, Monitor, TrendCharts, User, VideoPlay, Warning } from '@element-plus/icons-vue'
import { routes } from '../../router'
import { DATA_MODES } from '../../domain/constants'
import { getEvents, runtime, setDataMode } from '../../services/repository'

const route = useRoute()
const router = useRouter()
const collapsed = ref(true)
const mobileNavigationOpen = ref(false)
const openingEventDetail = ref(false)
const runtimeBannerVisible = ref(false)
let runtimeBannerTimer
const pagesBuild = import.meta.env.VITE_PAGES_BUILD === 'true'
const iconMap = { ChatLineRound, Clock, DataAnalysis, DocumentChecked, House, Monitor, TrendCharts, User, VideoPlay }
const groupConfig = [
  { label: '总览', paths: ['/'] },
  { label: '风险处置', paths: ['/events', '/events/:eventId', '/replay'] },
  { label: '关怀趋势', paths: ['/baseline', '/care', '/weekly'] },
  { label: '系统与材料', paths: ['/resident', '/system'] },
]
const navRoutes = routes.filter((item) => item.meta?.nav)
const navGroups = groupConfig.map((group) => ({ ...group, items: group.paths.map((path) => navRoutes.find((item) => item.path === path)).filter(Boolean) }))
const dataModeOptions = Object.entries(DATA_MODES)
  .filter(([value]) => value !== 'auto')
  .map(([value, label]) => ({ value, label }))
const selectedDataMode = computed(() => runtime.mode === 'replay' ? 'replay' : 'api')
const activePath = computed(() => ['event-detail', 'event-detail-empty'].includes(route.name) ? '/events/:eventId' : route.path)
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
    const latestEvent = events.reduce((latest, event) => (!latest || createdAtTimestamp(event) > createdAtTimestamp(latest) ? event : latest), null)
    if (!latestEvent) {
      ElMessage.error('风险事件调取失败：当前居民暂无可用事件')
      await router.push({ name: 'event-detail-empty', query: { reason: 'empty' } })
      return
    }
    await router.push({ name: 'event-detail', params: { eventId: latestEvent.event_id } })
  } catch {
    ElMessage.error('风险事件调取失败：后端接口服务不可达')
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
      <div v-show="!collapsed" class="guard-status" :class="{ degraded: runtime.degraded }" role="status" aria-live="polite">
        <span class="guard-status-icon"><el-icon><component :is="runtime.degraded ? Warning : CircleCheck" /></el-icon></span>
        <span>
          <strong>{{ runtime.degraded ? '离线回放模式' : '守护服务运行中' }}</strong>
          <small>{{ runtime.degraded ? '当前不代表实时设备状态' : '风险变化将进入统一事件流' }}</small>
        </span>
      </div>
    </aside>
    <div class="workspace">
      <div v-if="pagesBuild" class="public-demo-banner" role="status"><strong>脱敏评审演示</strong><span>授权回放</span><span>非实时设备</span><span>非老年人实测</span></div>
      <header class="topbar">
        <button class="mobile-menu-button" type="button" aria-label="打开导航" @click="mobileNavigationOpen = true"><el-icon><Menu /></el-icon></button>
        <div class="topbar-context">
          <div class="page-context"><span>{{ currentPage.group }}</span><strong>{{ currentPage.title }}</strong></div>
          <div class="context-divider" aria-hidden="true"></div>
          <div class="resident-identity"><el-avatar :size="36" class="resident-avatar">张</el-avatar><div><strong>张建国</strong><span>76岁 · 杭州家中</span></div></div>
        </div>
        <div class="topbar-actions">
          <el-segmented
            :model-value="selectedDataMode"
            :options="dataModeOptions"
            :disabled="pagesBuild"
            aria-label="数据连接模式"
            @change="setDataMode"
          />
          <div v-if="runtime.degraded" class="degraded-chip" role="status"><el-icon><Warning /></el-icon>后端降级</div>
        </div>
      </header>
      <Transition name="runtime-peek">
        <div v-if="runtime.message && runtimeBannerVisible" class="runtime-banner transient-runtime-banner" :class="{ degraded: runtime.degraded }" role="status"><el-icon><InfoFilled /></el-icon><span>{{ runtime.message }}</span><small v-if="runtime.activeSource === 'replay_dataset'">授权回放</small></div>
      </Transition>
      <main
        v-loading="openingEventDetail"
        element-loading-text="正在调取风险事件"
        class="main-content"
        data-testid="event-navigation-loading"
      ><router-view :key="`${route.fullPath}-${runtime.mode}`" /></main>
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
