<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ChartPanel from '../components/common/ChartPanel.vue'
import { getDashboard, getForewarningHistory, getLatestForewarning } from '../services/repository'
import { useResidentProfile } from '../services/residentProfile'
import { formatDateTime, formatPercent } from '../utils/format'

const dashboardLoading = ref(true)
const dashboardError = ref('')
const dashboard = ref(null)
const latestLoading = ref(true)
const latestError = ref('')
const latestForewarning = ref(null)
const historyLoading = ref(true)
const historyError = ref('')
const history = ref([])
const rangeMode = ref('all')
const customRange = ref([])
const currentPage = ref(1)
const pageSize = 20
const rangeOptions = [
  { label: '全部', value: 'all' }, { label: '24小时', value: '24h' },
  { label: '7天', value: '7d' }, { label: '30天', value: '30d' }, { label: '自定义', value: 'custom' },
]
const { profile, save: saveProfile, reset: resetProfile } = useResidentProfile()
const permissions = ['跌倒风险预警', '事件证据摘要', '授权片段回放', '家属反馈回写']
const resident = computed(() => dashboard.value?.resident || {})
const pageHistory = computed(() => history.value.slice((currentPage.value - 1) * pageSize, currentPage.value * pageSize))
const latestAttention = computed(() => {
  if (!latestForewarning.value) return 'UNKNOWN'
  return [latestForewarning.value.instant, latestForewarning.value.short_30s, latestForewarning.value.trend_3min]
    .sort((left, right) => right.engineering_index - left.engineering_index)[0].attention_level
})
const attentionConfig = {
  UNKNOWN: { label: '数据不足', type: 'info' }, GREEN: { label: '绿色观察', type: 'success' },
  YELLOW: { label: '黄色关注', type: 'warning' }, ORANGE: { label: '橙色干预', type: 'danger' },
}
const phaseLabels = { PERIODIC: '周期评估', PRE_INTERVENTION: '干预前', POST_INTERVENTION: '干预后' }
const chartOption = computed(() => {
  const points = [...history.value].sort((left, right) => Date.parse(left.evaluated_at) - Date.parse(right.evaluated_at))
  return {
    tooltip: { trigger: 'axis', valueFormatter: (value) => `${Math.round(value * 100)}%` },
    legend: { data: ['即时', '30秒', '3分钟'], bottom: 0 },
    grid: { left: 48, right: 20, top: 24, bottom: 52 },
    xAxis: { type: 'category', data: points.map((item) => formatDateTime(item.evaluated_at)), axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value', min: 0, max: 1, axisLabel: { formatter: (value) => `${Math.round(value * 100)}%` } },
    series: [
      { name: '即时', type: 'line', smooth: true, showSymbol: points.length < 30, data: points.map((item) => item.instant.engineering_index), color: '#b64f4f' },
      { name: '30秒', type: 'line', smooth: true, showSymbol: points.length < 30, data: points.map((item) => item.short_30s.engineering_index), color: '#c28a32' },
      { name: '3分钟', type: 'line', smooth: true, showSymbol: points.length < 30, data: points.map((item) => item.trend_3min.engineering_index), color: '#23706a' },
    ],
  }
})

function rangeParams() {
  if (rangeMode.value === 'all') return {}
  if (rangeMode.value === 'custom') {
    if (!Array.isArray(customRange.value) || customRange.value.length !== 2) return null
    return { from: new Date(customRange.value[0]).toISOString(), to: new Date(customRange.value[1]).toISOString() }
  }
  const durations = { '24h': 24 * 60 * 60 * 1000, '7d': 7 * 24 * 60 * 60 * 1000, '30d': 30 * 24 * 60 * 60 * 1000 }
  const to = new Date()
  return { from: new Date(to.getTime() - durations[rangeMode.value]).toISOString(), to: to.toISOString() }
}

async function loadDashboard() {
  dashboardLoading.value = true
  dashboardError.value = ''
  try { dashboard.value = await getDashboard() }
  catch (error) { dashboardError.value = `无法读取老人档案：${error.message}` }
  finally { dashboardLoading.value = false }
}

async function loadLatest() {
  latestLoading.value = true
  latestError.value = ''
  try { latestForewarning.value = await getLatestForewarning() }
  catch (error) { latestError.value = `无法读取最新预警：${error.message}` }
  finally { latestLoading.value = false }
}

async function loadHistory() {
  const params = rangeParams()
  if (params === null) { ElMessage.warning('请选择完整的开始和结束时间'); return }
  historyLoading.value = true
  historyError.value = ''
  currentPage.value = 1
  try { history.value = await getForewarningHistory(undefined, { ...params, limit: 500 }) }
  catch (error) { history.value = []; historyError.value = `无法读取预警历史：${error.message}` }
  finally { historyLoading.value = false }
}

function changeRange(mode) { if (mode !== 'custom') loadHistory() }
onMounted(() => { loadDashboard(); loadLatest(); loadHistory() })
</script>

<template>
  <div>
    <PageHeader title="老人档案与授权" description="管理必要档案，并查看当前预警摘要和历史工程指数。">
      <SourceBadge v-if="dashboard" :mode="dashboard.device.source_mode" :simulated="dashboard.device.simulated" />
    </PageHeader>
    <el-alert v-if="dashboardError" :title="dashboardError" type="error" :closable="false" show-icon />

    <div v-loading="dashboardLoading">
      <template v-if="dashboard">
        <section class="content-card" data-testid="resident-profile">
          <div class="card-heading"><div><span class="section-kicker">基本信息</span><h2>{{ profile.name }}</h2></div><el-tag type="success" effect="plain">已完成授权</el-tag></div>
          <div class="resident-profile-grid">
            <el-avatar :size="76">{{ profile.name.slice(0, 1) }}</el-avatar>
            <dl class="detail-list"><div><dt>关系</dt><dd>{{ profile.relation }}</dd></div><div><dt>年龄</dt><dd>{{ profile.age }} 岁</dd></div><div><dt>居住位置</dt><dd>{{ profile.location }}</dd></div><div><dt>居住情况</dt><dd>{{ profile.living }}</dd></div><div class="review-only"><dt>居民标识</dt><dd>{{ resident.resident_id || 'resident-001' }}</dd></div></dl>
          </div>
        </section>
      </template>
    </div>

    <section class="content-card latest-forewarning-card" data-testid="latest-forewarning" v-loading="latestLoading">
      <div class="card-heading"><div><span class="section-kicker">最新预警摘要</span><h2>居民当前工程观察</h2></div><el-tag v-if="latestForewarning" :type="attentionConfig[latestAttention]?.type" effect="plain">{{ attentionConfig[latestAttention]?.label }}</el-tag></div>
      <el-alert v-if="latestError" :title="latestError" type="error" :closable="false" show-icon />
      <template v-else-if="latestForewarning">
        <div class="forewarning-horizon-grid">
          <div><span>即时 · {{ latestForewarning.instant.window_seconds }}秒</span><strong>{{ formatPercent(latestForewarning.instant.engineering_index) }}</strong><small>{{ latestForewarning.instant.attention_level }}</small></div>
          <div><span>短时 · {{ latestForewarning.short_30s.window_seconds }}秒</span><strong>{{ formatPercent(latestForewarning.short_30s.engineering_index) }}</strong><small>{{ latestForewarning.short_30s.attention_level }}</small></div>
          <div><span>趋势 · {{ latestForewarning.trend_3min.window_seconds / 60 }}分钟</span><strong>{{ formatPercent(latestForewarning.trend_3min.engineering_index) }}</strong><small>{{ latestForewarning.trend_3min.attention_level }}</small></div>
        </div>
        <div class="latest-forewarning-meta">
          <dl class="detail-list compact-detail-list"><div><dt>评估时间</dt><dd>{{ formatDateTime(latestForewarning.evaluated_at) }}</dd></div><div><dt>评估状态</dt><dd>{{ latestForewarning.assessment_status }}</dd></div><div><dt>置信度</dt><dd>{{ latestForewarning.confidence_level }}</dd></div><div><dt>规则版本</dt><dd>{{ latestForewarning.ruleset_version }}</dd></div></dl>
          <SourceBadge :mode="latestForewarning.source_mode" :simulated="latestForewarning.simulated" />
        </div>
        <el-alert :title="latestForewarning.recommended_action" type="info" :closable="false" show-icon />
      </template>
      <el-empty v-else description="当前居民暂无预警摘要" :image-size="72" />
    </section>

    <section class="content-card forewarning-history-card" data-testid="forewarning-history">
      <div class="card-heading"><div><span class="section-kicker">预警历史</span><h2>工程指数趋势与记录</h2></div><el-tag type="info" effect="plain">{{ history.length }} 条</el-tag></div>
      <div class="history-filter-bar">
        <el-segmented v-model="rangeMode" :options="rangeOptions" aria-label="预警历史时间范围" @change="changeRange" />
        <div v-if="rangeMode === 'custom'" class="custom-range-controls">
          <el-date-picker v-model="customRange" type="datetimerange" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" unlink-panels />
          <el-button type="primary" @click="loadHistory">应用</el-button>
        </div>
      </div>
      <el-alert v-if="historyError" :title="historyError" type="error" :closable="false" show-icon />
      <div v-loading="historyLoading" class="history-content">
        <template v-if="history.length">
          <ChartPanel :option="chartOption" height="320px" aria-label="居民预警即时、30秒和3分钟工程指数趋势" />
          <el-table :data="pageHistory" height="420" class="forewarning-history-table">
            <el-table-column label="评估时间" min-width="176"><template #default="{ row }">{{ formatDateTime(row.evaluated_at) }}</template></el-table-column>
            <el-table-column label="阶段" width="100"><template #default="{ row }">{{ phaseLabels[row.phase] || row.phase }}</template></el-table-column>
            <el-table-column label="即时" width="84"><template #default="{ row }">{{ formatPercent(row.instant.engineering_index) }}</template></el-table-column>
            <el-table-column label="30秒" width="84"><template #default="{ row }">{{ formatPercent(row.short_30s.engineering_index) }}</template></el-table-column>
            <el-table-column label="3分钟" width="84"><template #default="{ row }">{{ formatPercent(row.trend_3min.engineering_index) }}</template></el-table-column>
            <el-table-column prop="assessment_status" label="状态" width="110" />
            <el-table-column label="来源" min-width="190"><template #default="{ row }"><SourceBadge :mode="row.source_mode" :simulated="row.simulated" /></template></el-table-column>
          </el-table>
          <el-pagination v-if="history.length > pageSize" v-model:current-page="currentPage" :page-size="pageSize" :total="history.length" layout="prev, pager, next, total" class="history-pagination" />
        </template>
        <el-empty v-else-if="!historyLoading" description="所选时间范围内暂无预警历史" :image-size="80" />
      </div>
    </section>

    <template v-if="dashboard">
      <section class="content-card questionnaire-card">
        <div class="card-heading"><div><span class="section-kicker">3分钟初始问卷</span><h2>风险画像与授权偏好</h2></div><el-tag type="warning" effect="plain">{{ profile.filledBy }} · 离线演示档案</el-tag></div>
        <el-form label-position="top" @change="saveProfile">
          <div class="questionnaire-grid">
            <el-form-item label="行动能力"><el-input v-model="profile.mobility" /></el-form-item><el-form-item label="关节/疼痛情况"><el-input v-model="profile.jointIssues" /></el-form-item><el-form-item label="既往跌倒"><el-input v-model="profile.fallHistory" /></el-form-item>
            <el-form-item label="起夜与头晕"><el-input v-model="profile.dizziness" /></el-form-item><el-form-item label="用药安排"><el-input v-model="profile.medication" /></el-form-item><el-form-item label="日常作息"><el-input v-model="profile.sleep" /></el-form-item>
            <el-form-item label="辅助器具与环境"><el-input v-model="profile.assistiveDevice" /></el-form-item><el-form-item label="通知策略"><el-input v-model="profile.noticeLevel" /></el-form-item><el-form-item label="紧急联系人"><el-input v-model="profile.emergencyContact" /></el-form-item>
            <el-form-item label="隐私区域"><el-input v-model="profile.privacyZones" /></el-form-item><el-form-item label="适老提醒语"><el-input v-model="profile.reminder" /></el-form-item>
          </div>
          <div class="consent-row"><el-checkbox v-model="profile.videoConsent" @change="saveProfile">同意授权视频用于风险复核</el-checkbox><el-checkbox v-model="profile.audioConsent" @change="saveProfile">同意授权音频用于本地关键词分析</el-checkbox></div>
          <div class="form-actions"><el-button type="primary" @click="saveProfile">保存问卷</el-button><el-button plain @click="resetProfile">恢复预设</el-button><span>答案仅保存在本机，不参与医学诊断或伪造个人基线。</span></div>
        </el-form>
      </section>
      <section class="content-card">
        <div class="card-heading"><div><span class="section-kicker">授权范围</span><h2>当前家属可查看和操作</h2></div></div>
        <div class="permission-list"><el-tag v-for="item in permissions" :key="item" type="success" effect="plain">{{ item }}</el-tag></div>
        <el-alert title="前端仅展示文档约定的事件与设备信息。" type="info" show-icon :closable="false" />
      </section>
    </template>
  </div>
</template>
