<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import ChartPanel from '../components/common/ChartPanel.vue'
import { getWeeklyReport, submitFamilyFeedback } from '../services/repository'
import { formatDateTime, formatPercent } from '../utils/format'

const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const report = ref(null)
const careChoice = ref('')
const verifyChoice = ref('')

const trendOption = computed(() => ({
  color: ['#176b65', '#9fb8b0', '#dd8a3c'],
  grid: { left: 48, right: 24, top: 48, bottom: 42 },
  tooltip: { trigger: 'axis' },
  legend: { data: ['活动指数', '个人基线', '作息偏移'], top: 0, textStyle: { color: '#54635f', fontSize: 14 } },
  xAxis: { type: 'category', data: report.value?.trend?.map((item) => item.date) || [], axisLabel: { color: '#64736f' } },
  yAxis: [
    { type: 'value', name: '活动指数', min: 0, max: 100, splitLine: { lineStyle: { color: '#edf3f1' } }, axisLabel: { color: '#64736f' } },
    { type: 'value', name: '分钟', min: 0, max: 40, splitLine: { show: false }, axisLabel: { color: '#64736f' } },
  ],
  series: [
    { name: '活动指数', type: 'line', smooth: true, symbolSize: 8, data: report.value?.trend?.map((item) => item.activity) || [], lineStyle: { width: 4 } },
    { name: '个人基线', type: 'line', symbol: 'none', data: report.value?.trend?.map((item) => item.baseline) || [], lineStyle: { width: 2, type: 'dashed' } },
    { name: '作息偏移', type: 'bar', yAxisIndex: 1, barWidth: 16, data: report.value?.trend?.map((item) => item.sleep_offset) || [], itemStyle: { borderRadius: [6, 6, 0, 0] } },
  ],
}))

async function load() {
  loading.value = true
  try {
    report.value = await getWeeklyReport()
  } catch (err) {
    error.value = `无法读取周报：${err.message}`
  } finally {
    loading.value = false
  }
}

async function submit(kind) {
  const currentStatus = kind === 'care' ? report.value?.care?.status : report.value?.visitor_case?.verification_status
  if (currentStatus === 'SUBMITTED') return
  const value = kind === 'care' ? careChoice.value : verifyChoice.value
  if (!value) {
    ElMessage.warning('请先选择一项反馈')
    return
  }
  submitting.value = true
  try {
    const options = kind === 'care'
      ? report.value?.care?.options || []
      : report.value?.visitor_case?.verification_options || []
    if (!options.length) {
      ElMessage.warning(kind === 'care' ? '当前没有可提交的关怀选项' : '当前没有可提交的核验选项')
      return
    }
    const eventId = kind === 'care' ? report.value.care?.event_id : report.value.visitor_case?.event_id
    if (!eventId) {
      ElMessage.warning('当前 API 未返回可关联的事件，无法提交反馈')
      return
    }
    const result = await submitFamilyFeedback(eventId, {
      feedback_type: 'confirm', value, operator: 'family',
      feedback_kind: kind === 'care' ? 'CARE' : 'IDENTITY_VERIFICATION',
    })
    if (kind === 'care') report.value.care = { ...report.value.care, status: 'SUBMITTED', feedback_record: result }
    else report.value.visitor_case = { ...report.value.visitor_case, verification_status: 'SUBMITTED', feedback_record: result }
    ElMessage.success('反馈已记录，将进入统一事件时间轴')
  } catch (err) {
    ElMessage.error(`提交失败：${err.message}`)
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="本周值得关注的变化" description="黄色趋势低打扰汇总给家属，不在老人侧即时报警。">
      <SourceBadge v-if="report" :mode="report.source_mode" :simulated="report.simulated" />
    </PageHeader>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <template v-if="report">
      <section class="weekly-summary" data-testid="weekly-summary">
        <div><RiskBadge :level="report.risk_level" /><h2>{{ report.summary }}</h2><p>报告周期：{{ report.period }} · 生成于 {{ formatDateTime(report.generated_at) }}</p></div>
        <div class="low-disturbance"><span>低打扰原则</span><strong>本周最多主动汇总一次</strong><p>趋势恶化时可以更新，但不会因单次变化制造焦虑。</p></div>
      </section>

      <section class="content-card weekly-chart-card">
        <div class="card-heading"><div><span class="section-kicker">个人趋势</span><h2>活动与作息变化</h2></div><span class="non-diagnosis">行为趋势，不是医学诊断</span></div>
        <ChartPanel v-if="report.trend.length" :option="trendOption" height="350px" aria-label="最近七天活动趋势、个人基线和作息偏移图" />
        <el-empty v-else description="当前 API 未提供周报趋势序列" />
      </section>

      <section class="weekly-columns">
        <article class="content-card care-panel" data-testid="care-panel">
          <div class="card-heading"><div><span class="section-kicker">家属关怀</span><h2>先看证据，再决定怎么联系</h2></div></div>
          <div v-if="report.evidence.length" class="weekly-evidence-list">
            <article v-for="item in report.evidence" :key="item.label">
              <span class="evidence-number">{{ formatPercent(item.confidence) }}</span>
              <div><strong>{{ item.label }}</strong><p>{{ item.detail }}</p></div>
            </article>
          </div>
          <el-empty v-else description="本周暂无可展示的趋势 Evidence" />
          <div class="recommendation-box">
            <strong>建议动作</strong>
            <ol><li v-for="item in report.recommendations" :key="item">{{ item }}</li></ol>
          </div>
          <fieldset class="feedback-fieldset">
            <legend>完成联系后，请选择反馈</legend>
            <el-radio-group v-model="careChoice" class="stacked-radios" :disabled="report.care.status === 'SUBMITTED'">
              <el-radio v-for="option in report.care.options" :key="option" :label="option" :value="option" border @click="careChoice = option">{{ option }}</el-radio>
            </el-radio-group>
            <el-alert v-if="!report.care.options.length" title="当前 API 未提供关怀选项" type="info" :closable="false" />
          </fieldset>
          <el-button data-testid="care-submit" type="primary" size="large" :loading="submitting" :disabled="report.care.status === 'SUBMITTED' || !report.care.options.length" @click="submit('care')">
            {{ report.care.status === 'SUBMITTED' ? '关怀反馈已记录' : '记录关怀反馈' }}
          </el-button>
          <div v-if="report.care.feedback_record" class="recorded-feedback" data-testid="care-record">
            <strong>已记录关怀反馈</strong><span>{{ report.care.feedback_record.value }}</span><small>{{ report.care.feedback_record.recorded_at }} · {{ report.care.feedback_record.operator }} · {{ report.care.feedback_record.saved_in_demo ? '本地演示记录' : '后端记录' }}</small>
          </div>
        </article>

        <article v-if="report.visitor_case" class="content-card visitor-panel" data-testid="visitor-panel">
          <div class="card-heading"><div><span class="section-kicker">访客核验</span><h2>{{ report.visitor_case.visitor_label }}</h2></div><RiskBadge :level="report.visitor_case.risk_level" compact /></div>
          <SourceBadge :mode="report.visitor_case.source_mode" :simulated="report.visitor_case.simulated" />
          <div class="visitor-meta"><span><b>{{ report.visitor_case.duration_minutes }}</b> 分钟停留</span><span>{{ report.visitor_case.location }}</span><span>{{ formatDateTime(report.visitor_case.occurred_at) }}</span></div>
          <div class="visitor-evidence">
            <article v-for="item in report.visitor_case.evidence" :key="item.type">
              <span></span><div><strong>{{ item.label }}</strong><p>{{ item.detail }}</p><code>{{ item.type }}</code></div>
            </article>
          </div>
          <div class="gentle-action"><strong>建议</strong><p>{{ report.visitor_case.recommended_action }}</p></div>
          <fieldset class="feedback-fieldset">
            <legend>联系确认后，请选择核验结果</legend>
            <el-radio-group v-model="verifyChoice" class="stacked-radios" :disabled="report.visitor_case.verification_status === 'SUBMITTED'">
              <el-radio v-for="option in report.visitor_case.verification_options" :key="option" :label="option" :value="option" border @click="verifyChoice = option">{{ option }}</el-radio>
            </el-radio-group>
          </fieldset>
          <el-button data-testid="verify-submit" type="primary" size="large" :loading="submitting" :disabled="report.visitor_case.verification_status === 'SUBMITTED' || !report.visitor_case.verification_options.length" @click="submit('verify')">
            {{ report.visitor_case.verification_status === 'SUBMITTED' ? '身份核验已记录' : '提交身份核验' }}
          </el-button>
          <div v-if="report.visitor_case.feedback_record" class="recorded-feedback" data-testid="identity-record">
            <strong>已记录身份核验</strong><span>{{ report.visitor_case.feedback_record.value }}</span><small>{{ report.visitor_case.feedback_record.recorded_at }} · {{ report.visitor_case.feedback_record.operator }} · {{ report.visitor_case.feedback_record.saved_in_demo ? '本地演示记录' : '后端记录' }}</small>
          </div>
        </article>
        <article v-else class="content-card visitor-panel api-empty-state" data-testid="visitor-panel-empty">
          <div class="card-heading"><div><span class="section-kicker">访客核验</span><h2>暂无访客事件</h2></div></div>
          <el-empty description="当前 API 未返回 visitor_case，不使用 Mock 访客数据填充" />
        </article>
      </section>
    </template>
  </div>
</template>
