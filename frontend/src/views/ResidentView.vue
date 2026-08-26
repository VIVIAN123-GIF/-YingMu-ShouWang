<script setup>
import { computed, onMounted, ref } from 'vue'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import { getDashboard } from '../services/repository'
import { useResidentProfile } from '../services/residentProfile'

const loading = ref(true)
const error = ref('')
const dashboard = ref(null)
const { profile, save: saveProfile, reset: resetProfile } = useResidentProfile()
const permissions = ['跌倒风险预警', '事件证据摘要', '授权片段回放', '家属反馈回写']
const resident = computed(() => dashboard.value?.resident || {})

async function load() {
  try { dashboard.value = await getDashboard() }
  catch (err) { error.value = `无法读取老人档案：${err.message}` }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="老人档案与授权" description="家属只管理必要信息和授权范围，账号凭证不会进入浏览器。">
      <SourceBadge v-if="dashboard" :mode="dashboard.device.source_mode" :simulated="dashboard.device.simulated" />
    </PageHeader>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="dashboard">
      <section class="content-card" data-testid="resident-profile">
        <div class="card-heading"><div><span class="section-kicker">基本信息</span><h2>{{ profile.name }}</h2></div><el-tag type="success" effect="plain">已完成授权</el-tag></div>
        <div class="resident-profile-grid">
          <el-avatar :size="76">{{ profile.name.slice(0, 1) }}</el-avatar>
          <dl class="detail-list"><div><dt>关系</dt><dd>{{ profile.relation }}</dd></div><div><dt>年龄</dt><dd>{{ profile.age }} 岁</dd></div><div><dt>居住位置</dt><dd>{{ profile.location }}</dd></div><div><dt>居住情况</dt><dd>{{ profile.living }}</dd></div><div class="review-only"><dt>居民标识</dt><dd>{{ resident.resident_id || 'resident-001' }}</dd></div></dl>
        </div>
      </section>
      <section class="content-card questionnaire-card">
        <div class="card-heading"><div><span class="section-kicker">3分钟初始问卷</span><h2>风险画像与授权偏好</h2></div><el-tag type="warning" effect="plain">{{ profile.filledBy }} · 离线演示档案</el-tag></div>
        <el-form label-position="top" @change="saveProfile">
          <div class="questionnaire-grid">
            <el-form-item label="行动能力"><el-input v-model="profile.mobility" /></el-form-item>
            <el-form-item label="关节/疼痛情况"><el-input v-model="profile.jointIssues" /></el-form-item>
            <el-form-item label="既往跌倒"><el-input v-model="profile.fallHistory" /></el-form-item>
            <el-form-item label="起夜与头晕"><el-input v-model="profile.dizziness" /></el-form-item>
            <el-form-item label="用药安排"><el-input v-model="profile.medication" /></el-form-item>
            <el-form-item label="日常作息"><el-input v-model="profile.sleep" /></el-form-item>
            <el-form-item label="辅助器具与环境"><el-input v-model="profile.assistiveDevice" /></el-form-item>
            <el-form-item label="通知策略"><el-input v-model="profile.noticeLevel" /></el-form-item>
            <el-form-item label="紧急联系人"><el-input v-model="profile.emergencyContact" /></el-form-item>
            <el-form-item label="隐私区域"><el-input v-model="profile.privacyZones" /></el-form-item>
            <el-form-item label="适老提醒语"><el-input v-model="profile.reminder" /></el-form-item>
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
