import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
const HomeView = () => import('../views/HomeView.vue')
const EventsView = () => import('../views/EventsView.vue')
const EventDetailView = () => import('../views/EventDetailView.vue')
const WeeklyView = () => import('../views/WeeklyView.vue')
const BaselineView = () => import('../views/BaselineView.vue')
const ResidentView = () => import('../views/ResidentView.vue')
const CareView = () => import('../views/CareView.vue')
const SystemView = () => import('../views/SystemView.vue')
const SceneCalibrationView = () => import('../views/SceneCalibrationView.vue')
const ReplayView = () => import('../views/ReplayView.vue')

const routes = [
  { path: '/', name: 'home', component: HomeView, meta: { title: '首页安全水位', nav: true, icon: 'House' } },
  { path: '/resident', name: 'resident', component: ResidentView, meta: { title: '老人档案与授权', nav: true, icon: 'User', description: '管理老人基本档案、隐私区域、家属授权和适老提醒语音。' } },
  { path: '/baseline', name: 'baseline', component: BaselineView, meta: { title: '个人基线与趋势', nav: true, icon: 'TrendCharts', description: '查看短、中、长期个人基线及活动热力图，异常时段不会写入正常基线。' } },
  { path: '/events', name: 'events', component: EventsView, meta: { title: '统一事件时间轴', nav: true, icon: 'Clock' } },
  { path: '/events/:eventId', name: 'event-detail', component: EventDetailView, meta: { title: '风险事件详情', nav: true, icon: 'DocumentChecked' } },
  { path: '/care', name: 'care', component: CareView, meta: { title: '家属关怀与身份核验', nav: true, icon: 'ChatLineRound', description: '承接家属关怀反馈、自愿筛查入口和访客身份核验结果。' } },
  { path: '/weekly', name: 'weekly', component: WeeklyView, meta: { title: '周报与核验', nav: true, icon: 'DataAnalysis' } },
  { path: '/system', name: 'system', component: SystemView, meta: { title: '系统和设备状态', nav: true, icon: 'Monitor', description: '展示设备在线状态、适配器模式、数据质量和未核验能力。' } },
  { path: '/system/calibration/:sceneConfigId', name: 'scene-calibration', component: SceneCalibrationView, meta: { title: '场景标定详情', nav: false } },
  { path: '/replay', name: 'replay', component: ReplayView, meta: { title: '场景回放', nav: true, icon: 'VideoPlay', description: '按故事顺序回放100天关键场景，并清楚标记真实、回放、公开数据或Mock来源。' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const routerMode = import.meta.env.VITE_ROUTER_MODE || 'history'
const history = routerMode === 'hash'
  ? createWebHashHistory(import.meta.env.BASE_URL)
  : createWebHistory(import.meta.env.BASE_URL)

const router = createRouter({
  history,
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = `${to.meta.title || '家属端'} · 萤目守望`
})

export default router
export { routerMode, routes }
