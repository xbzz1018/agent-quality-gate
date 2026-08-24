<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ value: string }>()

const labels: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  cancel_requested: '取消中',
  cancelled: '已取消',
  completed: '已完成',
  failed: '失败',
  ship: 'SHIP',
  warn: 'WARN',
  block: 'BLOCK',
  baseline: 'Baseline',
  candidate: 'Candidate',
  known: '已知',
  partial: '部分',
  unknown: 'UNKNOWN',
  http: 'HTTP',
  sse: 'SSE',
  ag_ui: 'AG-UI',
  a2a: 'A2A',
  mcp: 'MCP',
  active: '启用',
  disabled: '停用',
  revoked: '已撤销',
  success: '成功',
  failure: '失败',
}

const kind = computed(() => {
  if (['completed', 'ship', 'known', 'active', 'success'].includes(props.value)) return 'success'
  if (['running', 'candidate', 'http', 'sse'].includes(props.value)) return 'primary'
  if (['queued', 'warn', 'partial', 'baseline'].includes(props.value)) return 'warning'
  if (['failed', 'block', 'disabled', 'revoked', 'failure'].includes(props.value)) return 'danger'
  return 'info'
})
</script>

<template>
  <ElTag :type="kind" effect="light" size="small">{{ labels[value] ?? value }}</ElTag>
</template>
