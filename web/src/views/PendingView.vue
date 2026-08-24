<script setup lang="ts">
import { Construction } from '@lucide/vue'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const labels: Record<string, { title: string; status: string }> = {
  cost: { title: '用量与成本', status: 'Pending：聚合 API 与趋势图尚未进入 MVP 验收' },
  skills: { title: 'Skills 安全', status: 'Pending：Agent Skills 与 OPA/Rego 属于后置增强' },
  connections: { title: '系统连接', status: 'Pending：AG-UI、A2A 与 MCP Adapter 尚未实现' },
}
const content = computed(() => labels[String(route.params.area)] ?? labels.connections)
</script>

<template>
  <div class="page">
    <div class="page-header"><div><h1 class="page-title">{{ content.title }}</h1><p class="page-subtitle">能力状态以真实实现和测试为准</p></div></div>
    <section class="panel pending-panel"><Construction :size="30" /><strong>{{ content.status }}</strong><ElButton @click="$router.push('/runs')">返回评测运行</ElButton></section>
  </div>
</template>

<style scoped>
.pending-panel { min-height: 320px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; color: #667085; text-align: center; }
</style>
