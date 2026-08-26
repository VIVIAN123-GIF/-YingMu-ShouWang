<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatLineRound, Clock, DataAnalysis, DocumentChecked, Expand, Fold, House, InfoFilled, Menu, Monitor, MoreFilled, SwitchButton, TrendCharts, User, VideoPlay, Warning } from '@element-plus/icons-vue'
import { routes } from '../../router'
import { DATA_MODES } from '../../domain/constants'
import { getEvents, runtime, setDataMode } from '../../services/repository'
import { demoLoginConfig, logoutOfDemo } from '../../services/demoAuth'
import { VIEW_MODES, setViewMode, viewModeState } from '../../services/viewMode'

const emit = defineEmits(['logout'])
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const mobileNavigationOpen = ref(false)
const openingEventDetail = ref(false)
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
const activePath = computed(() => ['event-detail', 'event-detail-empty'].includes(route.name) ? '/events/:eventId' : route.path)

function logout() { logoutOfDemo(); emit('logout') }
function createdAtTimestamp(event) { const timestamp = Date.parse(event?.created_at || ''); return Number.isNaN(timestamp) ? 0 : timestamp }

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
    ElMessage.error('风险事件调取失败：FastAPI 服务不可达')
    await router.push({ name: 'event-detail-empty', query: { reason: 'unavailable' } })
  } finally { openingEventDetail.value = false }
}
</script>

<template>
  <div class="app-shell" :data-view-mode="viewModeState.mode">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand"><div class="brand-mark" aria-hidden="true">萤</div><div v-show="!collapsed" class="brand-copy"><strong>萤目守望</strong><span>统一家属端</span></div></div>
      <nav class="navigation-groups" aria-label="主导航">
        <section v-for="group in navGroups" :key="group.label" class="navigation-group">
          <span v-show="!collapsed" class="navigation-label">{{ group.label }}</span>
          <button v-for="item in group.items" :key="item.path" type="button" class="navigation-item" :class="{ active: activePath === item.path }" :aria-current="activePath === item.path ? 'page' : undefined" @click="handleSelect(item.path)">
            <el-icon><component :is="iconMap[item.meta.icon]" /></el-icon><span v-show="!collapsed">{{ item.meta.title }}</span>
          </button>
        </section>
      </nav>
      <button class="collapse-button" type="button" :aria-label="collapsed ? '展开导航' : '收起导航'" @click="collapsed = !collapsed"><el-icon><component :is="collapsed ? Expand : Fold" /></el-icon><span v-show="!collapsed">收起导航</span></button>
    </aside>

    <div class="workspace">
      <div v-if="pagesBuild" class="public-demo-banner" role="status"><strong>脱敏评审演示</strong><span>RECORDED_REPLAY / 授权回放</span><span>非实时设备</span><span>非老年人实测</span></div>
      <header class="topbar">
        <button class="mobile-menu-button" type="button" aria-label="打开导航" @click="mobileNavigationOpen = true"><el-icon><Menu /></el-icon></button>
        <div class="resident-identity"><el-avatar :size="40" class="resident-avatar">张</el-avatar><div><strong>张建国</strong><span>76岁 · 杭州家中</span></div></div>
        <div class="topbar-actions">
          <el-segmented :model-value="viewModeState.mode" :options="Object.entries(VIEW_MODES).map(([value, label]) => ({ value, label }))" aria-label="切换展示视图" @change="setViewMode" />
          <div v-if="runtime.degraded" class="degraded-chip" role="status"><el-icon><Warning /></el-icon>后端降级</div>
          <el-dropdown trigger="click">
            <el-button class="more-button" circle aria-label="数据与会话设置"><el-icon><MoreFilled /></el-icon></el-button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item v-if="!pagesBuild" disabled>数据模式：{{ DATA_MODES[runtime.mode] }}</el-dropdown-item>
              <el-dropdown-item v-if="!pagesBuild" v-for="(label, value) in DATA_MODES" :key="value" @click="setDataMode(value)">{{ label }}</el-dropdown-item>
              <el-dropdown-item v-if="demoLoginConfig.enabled" divided @click="logout"><el-icon><SwitchButton /></el-icon>退出评审入口</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
        </div>
      </header>
      <div v-if="runtime.message" class="runtime-banner" :class="{ degraded: runtime.degraded }" role="status"><el-icon><InfoFilled /></el-icon><span>{{ runtime.message }}</span><small v-if="runtime.activeSource === 'replay_dataset'">RECORDED_REPLAY / 授权回放</small></div>
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
