<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '../components/common/PageHeader.vue'
import SourceBadge from '../components/common/SourceBadge.vue'

const route = useRoute()
const title = computed(() => route.meta.title)
const description = computed(() => route.meta.description || '该页面已纳入统一信息架构。')
</script>

<template>
  <div>
    <PageHeader :title="title" :description="description">
      <SourceBadge mode="MOCK" :simulated="true" />
    </PageHeader>
    <section class="prototype-card">
      <div class="prototype-visual" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
      <div>
        <el-tag type="info" effect="plain" size="large">低保真原型</el-tag>
        <h2>{{ title }}已建立路由与页面骨架</h2>
        <p>{{ description }}</p>
        <p>后续数据将继续复用统一 FastAPI 接口、Evidence 结构和风险状态机，不会建设独立业务后台。</p>
      </div>
    </section>
  </div>
</template>
