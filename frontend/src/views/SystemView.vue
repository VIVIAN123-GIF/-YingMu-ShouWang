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
    <template v-if="device"><section class="content-card" data-testid="system-status"><div class="card-heading"><div><span class="section-kicker">设备状态</span><h2>{{ device.device_alias }}</h2></div><el-tag :type="device.online ? 'success' : 'danger'" size="large">{{ device.online ? '设备在线' : '设备离线' }}</el-tag></div><dl class="detail-list"><div><dt>适配器模式</dt><dd>{{ device.adapter_mode }}</dd></div><div><dt>数据来源</dt><dd>{{ device.source_mode }}</dd></div><div><dt>采集状态</dt><dd>{{ device.collection_active ? '采集运行中' : '采集已停止' }}</dd></div><div><dt>设备别名</dt><dd>{{ device.device_alias }}</dd></div></dl><SourceBadge :mode="device.source_mode" :simulated="device.simulated" /></section></template>
  </div>
</template>
