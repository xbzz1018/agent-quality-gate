<script setup lang="ts">
import { ArrowLeft, Ban, CheckCircle2, CircleAlert } from '@lucide/vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'
import { api, apiError } from '@/services/api'
import type { EvalRun, GatePolicy, GateResult } from '@/types/api'
import { formatDate, pretty } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const runId = Number(route.params.id)
const run = ref<EvalRun | null>(null)
const gate = ref<GateResult | null>(null)
const baselineRequired = ref(false)
const policy = ref<GatePolicy | null>(null)
const loading = ref(true)

const icon = computed(() => gate.value?.decision === 'ship' ? CheckCircle2 : gate.value?.decision === 'warn' ? CircleAlert : Ban)
const message = computed(() => {
  if (gate.value?.decision === 'ship') return '候选版本满足当前发布策略，可以发布。'
  if (gate.value?.decision === 'warn') return '候选版本可继续流程，但存在需要确认的性能或成本增长。'
  return '候选版本触发阻断规则，不应发布。'
})

onMounted(async () => {
  try {
    const [runRow, gateRow, policies] = await Promise.all([api.run(runId), api.gate(runId), api.policies()])
    run.value = runRow
    if ('status' in gateRow) {
      baselineRequired.value = true
    } else {
      gate.value = gateRow
      policy.value = policies.find((item) => item.id === gateRow.policy_id) ?? null
    }
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
      <div><ElButton link @click="router.push(`/runs/${runId}`)"><ArrowLeft :size="14" /> 返回运行详情</ElButton><h1 class="page-title gate-title">发布门禁</h1><p class="page-subtitle">Run #{{ runId }} · 版本化策略与实际触发值</p></div>
      <ElButton v-if="!baselineRequired" @click="router.push(`/runs/${runId}/comparison`)">查看版本对比</ElButton>
    </div>

    <section v-if="baselineRequired" class="panel baseline-required"><EmptyState title="需要 Baseline 才能执行发布门禁" description="当前运行只刻画 Candidate 质量，平台不会生成 SHIP、WARN 或 BLOCK。" /></section>

    <section v-if="gate" class="gate-decision" :class="`gate-decision--${gate.decision}`">
      <component :is="icon" :size="38" />
      <div><div class="gate-label">发布决策</div><div class="gate-word">{{ gate.decision.toUpperCase() }}</div><p>{{ message }}</p></div>
      <div class="gate-meta"><span>策略版本</span><strong>{{ policy ? `${policy.name} · ${policy.version}` : `Policy #${gate.policy_id}` }}</strong><span>评估时间</span><strong>{{ formatDate(gate.evaluated_at) }}</strong></div>
    </section>

    <div v-if="gate" class="gate-grid">
      <section class="panel"><div class="panel-header"><h2 class="panel-title">触发规则</h2><StatusTag :value="gate.decision" /></div><ElTable v-if="gate.reasons.length" :data="gate.reasons"><ElTableColumn prop="rule_id" label="规则 ID" min-width="170"><template #default="{ row }"><span class="mono">{{ row.rule_id }}</span></template></ElTableColumn><ElTableColumn label="级别" width="90"><template #default="{ row }"><StatusTag :value="row.severity" /></template></ElTableColumn><ElTableColumn label="阈值" min-width="100"><template #default="{ row }">{{ row.threshold }}</template></ElTableColumn><ElTableColumn label="实际值" min-width="100"><template #default="{ row }"><strong>{{ row.actual }}</strong></template></ElTableColumn></ElTable><div v-else class="ship-empty"><CheckCircle2 :size="24" /><strong>没有触发 WARN 或 BLOCK 规则</strong></div></section>
      <section class="panel"><div class="panel-header"><h2 class="panel-title">策略快照</h2><span class="muted">不可变版本</span></div><div class="panel-body"><h3 class="policy-heading">Thresholds</h3><pre class="json-block">{{ pretty(policy?.thresholds ?? {}) }}</pre><h3 class="policy-heading">Metric Deltas</h3><pre class="json-block">{{ pretty(gate.metric_deltas) }}</pre></div></section>
    </div>
  </div>
</template>

<style scoped>
.gate-title { margin-top: 4px; }
.gate-decision { min-height: 154px; display: grid; grid-template-columns: 48px minmax(0, 1fr) minmax(240px, .6fr); align-items: center; gap: 16px; margin-bottom: 14px; padding: 20px 22px; border: 1px solid; border-radius: 8px; background: white; }
.gate-decision--ship { color: #08795b; border-color: #a8dbc9; background: #f2fbf7; }
.gate-decision--warn { color: #985600; border-color: #f0c36a; background: #fff9e8; }
.gate-decision--block { color: #b32929; border-color: #efb3b3; background: #fff5f5; }
.gate-label { font-size: 11px; font-weight: 650; }
.gate-word { margin-top: 2px; font-size: 31px; line-height: 38px; font-weight: 800; }
.gate-decision p { margin: 4px 0 0; color: #475467; font-size: 12px; }
.gate-meta { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 7px 10px; padding-left: 18px; border-left: 1px solid currentColor; color: #475467; font-size: 11px; }
.gate-meta span { color: var(--muted); }
.gate-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(360px, .8fr); gap: 14px; }
.ship-empty { min-height: 210px; display: flex; align-items: center; justify-content: center; gap: 10px; color: var(--success); font-size: 12px; }
.policy-heading { margin: 2px 0 7px; font-size: 11px; }
.policy-heading + .json-block { margin-bottom: 14px; }
.baseline-required { min-height: 320px; display: grid; place-items: center; }
@media (max-width: 900px) { .gate-grid { grid-template-columns: 1fr; } .gate-decision { grid-template-columns: 42px 1fr; } .gate-meta { grid-column: 1 / -1; padding: 12px 0 0; border-top: 1px solid currentColor; border-left: 0; } }
</style>
