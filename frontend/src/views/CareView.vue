<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '../components/common/PageHeader.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import { getWeeklyReport, submitFamilyFeedback } from '../services/repository'
import { feedbackTone } from '../utils/format'

const loading = ref(true)
const error = ref('')
const report = ref(null)
const choice = ref('')
const submitted = ref(false)
async function load() { try { report.value = await getWeeklyReport(); submitted.value = report.value?.care?.status === 'SUBMITTED' } catch (err) { error.value = `无法读取关怀建议：${err.message}` } finally { loading.value = false } }
async function submit() {
  if (!choice.value || !report.value?.care?.event_id) return ElMessage.warning('请选择反馈，且当前事件必须可关联')
  try {
    const result = await submitFamilyFeedback(report.value.care.event_id, { feedback_type: 'confirm', value: choice.value, operator: 'family', feedback_kind: 'CARE' })
    report.value.care = { ...report.value.care, status: 'SUBMITTED', feedback_record: result }
    submitted.value = true
    ElMessage.success('关怀反馈已记录')
  } catch (err) { ElMessage.error(`记录失败：${err.message}`) }
}
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="家属关怀与身份核验" description="先看变化和建议，再记录一次明确、低打扰的联系结果。"><SourceBadge v-if="report" :mode="report.source_mode" :simulated="report.simulated" /></PageHeader>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="report">
      <section class="care-workspace">
        <article class="content-card" data-testid="care-workbench">
          <div class="card-heading"><div><span class="section-kicker">当前关怀建议</span><h2>{{ report.summary }}</h2></div><RiskBadge :level="report.risk_level" /></div>
          <p>{{ report.recommendations?.[0] || '本周暂无主动联系建议。' }}</p>
          <fieldset class="feedback-fieldset"><legend>联系后记录结果</legend><el-radio-group v-model="choice" class="stacked-radios" :disabled="submitted"><el-radio v-for="item in report.care.options" :key="item" :label="item" :value="item" border>{{ item }}</el-radio></el-radio-group></fieldset>
          <el-button type="primary" size="large" :disabled="submitted || !report.care.options.length" @click="submit">{{ submitted ? '关怀反馈已记录' : '记录关怀反馈' }}</el-button>
          <div v-if="report.care.feedback_record" class="recorded-feedback" :class="`feedback-${feedbackTone(report.care.feedback_record.value)}`" data-testid="care-record">
            <strong>已记录关怀反馈</strong><span>{{ report.care.feedback_record.value }}</span><small>{{ report.care.feedback_record.recorded_at }} · {{ report.care.feedback_record.operator }} · 本地演示记录</small>
          </div>
        </article>
        <article v-if="report.visitor_case" class="content-card">
          <div class="card-heading"><div><span class="section-kicker">访客核验</span><h2>{{ report.visitor_case.visitor_label }}</h2></div><RiskBadge :level="report.visitor_case.risk_level" /></div>
          <SourceBadge :mode="report.visitor_case.source_mode" :simulated="report.visitor_case.simulated" /><p>{{ report.visitor_case.recommended_action }}</p>
          <el-button plain @click="$router.push('/weekly')">查看完整核验卡</el-button>
          <div v-if="report.visitor_case.feedback_record" class="recorded-feedback" :class="`feedback-${feedbackTone(report.visitor_case.feedback_record.value)}`" data-testid="identity-record">
            <strong>已记录身份核验</strong><span>{{ report.visitor_case.feedback_record.value }}</span><small>{{ report.visitor_case.feedback_record.recorded_at }} · {{ report.visitor_case.feedback_record.operator }} · 本地演示记录</small>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>
