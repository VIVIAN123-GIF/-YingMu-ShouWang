<script setup>
import { computed, onMounted, ref } from 'vue'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import { getDashboard } from '../services/repository'

const loading = ref(true)
const error = ref('')
const dashboard = ref(null)
const profile = { name: '张建国', age: 76, relation: '父亲', location: '杭州 · 家中', avatar: '张' }
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
          <el-avatar :size="76">{{ profile.avatar }}</el-avatar>
          <dl class="detail-list"><div><dt>关系</dt><dd>{{ profile.relation }}</dd></div><div><dt>年龄</dt><dd>{{ profile.age }} 岁</dd></div><div><dt>居住位置</dt><dd>{{ profile.location }}</dd></div><div><dt>居民标识</dt><dd>{{ resident.resident_id || 'resident-001' }}</dd></div></dl>
        </div>
      </section>
      <section class="content-card">
        <div class="card-heading"><div><span class="section-kicker">授权范围</span><h2>当前家属可查看和操作</h2></div></div>
        <div class="permission-list"><el-tag v-for="item in permissions" :key="item" type="success" effect="plain">{{ item }}</el-tag></div>
        <el-alert title="素材按事件授权访问；前端不会保存萤石主账号、AccessToken 或永久播放地址。" type="info" show-icon :closable="false" />
      </section>
    </template>
  </div>
</template>
