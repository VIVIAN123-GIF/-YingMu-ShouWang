<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ChatLineRound, Clock, DataAnalysis, DocumentChecked, Expand, Fold, House,
  InfoFilled, Monitor, TrendCharts, User, VideoPlay, Warning,
} from '@element-plus/icons-vue'
import { routes } from '../../router'
import { DATA_MODES } from '../../domain/constants'
import { getEvents, runtime, setDataMode } from '../../services/repository'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const openingEventDetail = ref(false)
const navRoutes = routes.filter((item) => item.meta?.nav)
const iconMap = { ChatLineRound, Clock, DataAnalysis, DocumentChecked, House, Monitor, TrendCharts, User, VideoPlay }
const activePath = computed(() => route.name === 'event-detail' ? '/events/:eventId' : route.path)

function createdAtTimestamp(event) {
  const timestamp = Date.parse(event?.created_at || '')
  return Number.isNaN(timestamp) ? 0 : timestamp
}

async function handleSelect(path) {
  if (path !== '/events/:eventId') {
    await router.push(path)
    return
  }

  if (route.name === 'event-detail' && route.params.eventId) return
  if (openingEventDetail.value) return

  openingEventDetail.value = true
  try {
    const events = await getEvents()
    const latestEvent = events.reduce((latest, event) => (
      !latest || createdAtTimestamp(event) > createdAtTimestamp(latest) ? event : latest
    ), null)

    if (!latestEvent) {
      ElMessage.info('暂无风险事件，请先等待风险事件生成')
      await router.push('/events')
      return
    }

    await router.push({ name: 'event-detail', params: { eventId: latestEvent.event_id } })
  } catch {
    ElMessage.error('无法读取风险事件，请稍后重试')
  } finally {
    openingEventDetail.value = false
  }
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">萤</div>
        <div v-show="!collapsed" class="brand-copy">
          <strong>萤目守望</strong>
          <span>统一家属端</span>
        </div>
      </div>

      <el-menu
        class="navigation"
        :default-active="activePath"
        :collapse="collapsed"
        :collapse-transition="false"
        @select="handleSelect"
      >
        <el-menu-item v-for="item in navRoutes" :key="item.path" :index="item.path">
          <el-icon><component :is="iconMap[item.meta.icon]" /></el-icon>
          <template #title>{{ item.meta.title }}</template>
        </el-menu-item>
      </el-menu>

      <button class="collapse-button" type="button" @click="collapsed = !collapsed">
        <el-icon><component :is="collapsed ? Expand : Fold" /></el-icon>
        <span v-show="!collapsed">收起导航</span>
      </button>
    </aside>

    <div class="workspace">
      <header class="topbar">
        <div class="resident-identity">
          <el-avatar :size="46" class="resident-avatar">张</el-avatar>
          <div>
            <strong>张建国</strong>
            <span>76岁 · 杭州家中 · 家属端</span>
          </div>
        </div>

        <div class="topbar-actions">
          <div v-if="runtime.degraded" class="degraded-chip" role="status">
            <el-icon><Warning /></el-icon>
            后端降级
          </div>
          <label class="mode-picker">
            <span>数据模式</span>
            <el-select :model-value="runtime.mode" aria-label="选择数据模式" @change="setDataMode">
              <el-option v-for="(label, value) in DATA_MODES" :key="value" :label="label" :value="value" />
            </el-select>
          </label>
        </div>
      </header>

      <div v-if="runtime.message" class="runtime-banner" :class="{ degraded: runtime.degraded }" role="status">
        <el-icon><InfoFilled /></el-icon>
        <span>{{ runtime.message }}</span>
        <small v-if="runtime.activeSource === 'mock'">页面数据已标记为 MOCK / 模拟实验</small>
      </div>

      <main class="main-content">
        <router-view :key="`${route.fullPath}-${runtime.mode}`" />
      </main>
    </div>
  </div>
</template>
