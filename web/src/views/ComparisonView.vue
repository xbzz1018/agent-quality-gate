<script setup lang="ts">
import { ArrowLeft, ShieldCheck } from '@lucide/vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import MetricCompareChart from '@/components/MetricCompareChart.vue'
import EmptyState from '@/components/EmptyState.vue'
import { api, apiError } from '@/services/api'
import type { CaseResult, Comparison, EvalRun } from '@/types/api'
import { formatCost, formatNumber, formatPercent } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const runId = Number(route.params.id)
const run = ref<EvalRun | null>(null)
const comparison = ref<Comparison | null>(null)
const baselineRequired = ref(false)
const results = ref<CaseResult[]>([])
const loading = ref(true)

const chartData = computed(() => ({
  labels: ['任务成功率', '工具参数准确率'],
  baseline: [
    (comparison.value?.baseline.success_rate ?? 0) * 100,
    (comparison.value?.baseline.tool_argument_accuracy ?? 0) * 100,
  ],
  candidate: [
    (comparison.value?.candidate.success_rate ?? 0) * 100,
    (comparison.value?.candidate.tool_argument_accuracy ?? 0) * 100,
  ],
}))
const failures = computed(() => {
  const counts = new Map<string, number>()
  for (const result of results.value.filter((item) => item.version_role === 'candidate' && item.failure_type)) {
    const key = result.failure_type ?? 'unknown'
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return [...counts].map(([type, count]) => ({ type, count }))
})

function delta(current: number | null, baseline: number | null, percent = false): string {
  if (current == null || baseline == null) return 'UNKNOWN'
  const value = current - baseline
  return `${value > 0 ? '+' : ''}${percent ? (value * 100).toFixed(1) + ' pp' : value.toFixed(0)}`
}

onMounted(async () => {
  try {
    const [runRow, comparisonRow, resultRows] = await Promise.all([
      api.run(runId), api.comparison(runId), api.results(runId),
    ])
    run.value = runRow
    results.value = resultRows
    if (comparisonRow.status === 'baseline_required') baselineRequired.value = true
    else comparison.value = comparisonRow
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-header">
      <div><ElButton link @click="router.push(`/runs/${runId}`)"><ArrowLeft :size="14" /> 返回运行详情</ElButton><h1 class="page-title compare-title">Baseline / Candidate 对比</h1><p class="page-subtitle">Run #{{ runId }} · 指标全部来自持久化 CaseResult</p></div>
      <ElButton v-if="!baselineRequired" type="primary" @click="router.push(`/runs/${runId}/gate`)"><ShieldCheck :size="15" /> 查看发布门禁</ElButton>
    </div>

    <section v-if="baselineRequired" class="panel baseline-required"><EmptyState title="需要 Baseline 才能进行版本对比" description="当前运行是 Candidate-only 特征评测，平台不会构造虚假的 Baseline 或发布决策。" /></section>

    <div v-if="comparison" class="metric-strip">
      <div class="metric"><div class="metric-label">Candidate 成功率</div><div class="metric-value">{{ formatPercent(comparison.candidate.success_rate) }}</div><div class="metric-detail">相对 Baseline {{ delta(comparison.candidate.success_rate, comparison.baseline.success_rate, true) }}</div></div>
      <div class="metric"><div class="metric-label">工具参数准确率</div><div class="metric-value">{{ formatPercent(comparison.candidate.tool_argument_accuracy) }}</div><div class="metric-detail">阈值由 Gate Policy 决定</div></div>
      <div class="metric"><div class="metric-label">Candidate P95 延迟</div><div class="metric-value">{{ formatNumber(comparison.candidate.p95_latency_ms, 'ms') }}</div><div class="metric-detail">差值 {{ delta(comparison.candidate.p95_latency_ms, comparison.baseline.p95_latency_ms) }}ms</div></div>
      <div class="metric"><div class="metric-label">Candidate 平均成本</div><div class="metric-value cost-value">{{ formatCost(comparison.candidate.average_model_cost) }}</div><div class="metric-detail">缺失用量或价格时为 UNKNOWN</div></div>
    </div>

    <div v-if="comparison" class="comparison-grid">
      <section class="panel"><div class="panel-header"><h2 class="panel-title">质量指标</h2></div><MetricCompareChart :labels="chartData.labels" :baseline="chartData.baseline" :candidate="chartData.candidate" /></section>
      <section class="panel"><div class="panel-header"><h2 class="panel-title">精确指标差值</h2></div><ElTable :data="[
        { metric: '任务成功率', baseline: formatPercent(comparison.baseline.success_rate), candidate: formatPercent(comparison.candidate.success_rate), change: delta(comparison.candidate.success_rate, comparison.baseline.success_rate, true) },
        { metric: '工具参数准确率', baseline: formatPercent(comparison.baseline.tool_argument_accuracy), candidate: formatPercent(comparison.candidate.tool_argument_accuracy), change: delta(comparison.candidate.tool_argument_accuracy, comparison.baseline.tool_argument_accuracy, true) },
        { metric: '安全违规', baseline: comparison.baseline.safety_violations, candidate: comparison.candidate.safety_violations, change: delta(comparison.candidate.safety_violations, comparison.baseline.safety_violations) },
        { metric: 'P95 延迟', baseline: formatNumber(comparison.baseline.p95_latency_ms, 'ms'), candidate: formatNumber(comparison.candidate.p95_latency_ms, 'ms'), change: delta(comparison.candidate.p95_latency_ms, comparison.baseline.p95_latency_ms) + 'ms' },
      ]"><ElTableColumn prop="metric" label="指标" min-width="130" /><ElTableColumn prop="baseline" label="Baseline" min-width="110" /><ElTableColumn prop="candidate" label="Candidate" min-width="110" /><ElTableColumn prop="change" label="变化" min-width="100" /></ElTable></section>
    </div>

    <section v-if="!baselineRequired" class="panel failure-panel">
      <div class="panel-header"><h2 class="panel-title">Candidate 失败分类</h2><span class="muted">{{ failures.reduce((sum, item) => sum + item.count, 0) }} 个失败结果</span></div>
      <ElTable v-if="failures.length" :data="failures"><ElTableColumn prop="type" label="失败类型" min-width="240" /><ElTableColumn prop="count" label="数量" width="100" /></ElTable>
      <div v-else class="no-failures">没有 Candidate 失败分类</div>
    </section>
  </div>
</template>

<style scoped>
.compare-title { margin-top: 4px; }
.comparison-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(420px, .95fr); gap: 14px; }
.failure-panel { margin-top: 14px; }
.cost-value { font-size: 17px; }
.no-failures { padding: 38px; color: var(--muted); font-size: 12px; text-align: center; }
.baseline-required { min-height: 320px; display: grid; place-items: center; }
@media (max-width: 1050px) { .comparison-grid { grid-template-columns: 1fr; } }
</style>
