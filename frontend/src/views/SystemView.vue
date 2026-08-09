<script setup>
import { onMounted, ref } from 'vue'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'
import { getDeviceStatus } from '../services/repository'

const loading = ref(true)
const error = ref('')
const device = ref(null)
async function load() { try { device.value = await getDeviceStatus() } catch (err) { error.value = `无法读取设备状态：${err.message}` } finally { loading.value = false } }
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="系统和设备状态" description="展示设备在线状态、适配器模式、数据质量和尚未核验的能力"><SourceBadge v-if="device" :mode="device.source_mode" :simulated="device.simulated" /></PageHeader>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="device"><section class="content-card" data-testid="system-status"><div class="card-heading"><div><span class="section-kicker">设备状态</span><h2>{{ device.name }}</h2></div><el-tag :type="device.online ? 'success' : 'danger'" size="large">{{ device.online ? '在线' : '离线' }}</el-tag></div><dl class="detail-list"><div><dt>适配器</dt><dd>{{ device.adapter }}</dd></div><div><dt>最后在线</dt><dd>{{ device.last_seen || '暂无' }}</dd></div><div><dt>数据质量</dt><dd>{{ device.data_quality == null ? '暂无' : `${Math.round(device.data_quality * 100)}%` }}</dd></div><div><dt>直播/素材状态</dt><dd>{{ device.stream_status || '按事件授权访问' }}</dd></div></dl></section><section class="content-card"><div class="card-heading"><div><span class="section-kicker">能力核验</span><h2>当前接口能力</h2></div></div><div class="permission-list"><el-tag v-for="item in (device.capabilities || [])" :key="item" type="success" effect="plain">{{ item }}</el-tag><el-tag v-for="item in (device.unverified_capabilities || [])" :key="item" type="warning" effect="plain">{{ item }} · 待核验</el-tag></div></section></template>
  </div>
</template>
