<script setup>
import { InfoFilled, VideoCamera } from '@element-plus/icons-vue'

defineProps({
  events: { type: Array, default: () => [] },
})

const selectedId = defineModel({ type: String, default: '' })
const emit = defineEmits(['select'])
</script>

<template>
  <section class="content-card replay-selector">
    <div class="replay-selector-head">
      <div class="replay-selector-title">
        <el-icon><VideoCamera /></el-icon>
        <h2>100 天关键片段</h2>
      </div>
      <el-select v-model="selectedId" aria-label="选择回放场景" @change="emit('select', $event)">
        <el-option
          v-for="(event, index) in events"
          :key="event.event_id"
          :label="`${index + 1}. ${event.title}`"
          :value="event.event_id"
        />
      </el-select>
    </div>
    <p><el-icon><InfoFilled /></el-icon><span>回放不会触发真实干预，也不会改变后端风险状态。</span></p>
  </section>
</template>

<style scoped>
.replay-selector {
  margin-bottom: 20px;
  padding: 24px;
  text-align: left;
  background: #fff;
  border: 0;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.replay-selector-head {
  padding-bottom: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  border-bottom: 1px solid #e5e7eb;
}

.replay-selector-title {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}

.replay-selector-title .el-icon {
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  color: #1677c2;
  background: #e8f4fc;
  border-radius: 9px;
  font-size: 21px;
}

.replay-selector-title h2 {
  margin: 0;
  color: #1d2129;
  font-size: 18px;
  line-height: 1.35;
  font-weight: 600;
  white-space: nowrap;
}

.replay-selector :deep(.el-select) {
  flex: 0 0 480px;
  width: 480px;
  margin: 0;
}

.replay-selector :deep(.el-select__wrapper) {
  min-height: 50px;
  padding: 0 16px;
  font-size: 16px;
}

.replay-selector :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px #1677c2 inset;
}

.replay-selector > p {
  margin: 17px 0 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #6b7280;
  font-size: 12px;
  line-height: 1.5;
}

.replay-selector > p .el-icon {
  flex: 0 0 auto;
  color: #6b7280;
  font-size: 16px;
}

@media (max-width: 767px) {
  .replay-selector {
    padding: 22px 18px;
  }

  .replay-selector-head {
    align-items: stretch;
    flex-direction: column;
  }

  .replay-selector-title h2 {
    white-space: normal;
  }

  .replay-selector :deep(.el-select) {
    flex: 0 0 auto;
    width: 100%;
  }
}
</style>
