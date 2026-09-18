<script setup lang="ts">
import { ArrowLeft, ExternalLink, RefreshCw, RotateCcw, Square } from '@lucide/vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '@/components/EmptyState.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api, apiError } from '@/services/api'
import type { CaseResult, Dataset, EvalRun, RunEvent } from '@/types/api'
import { formatCost, formatDate, formatNumber, pretty } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const runId = Number(route.params.id)
const run = ref<EvalRun | null>(null)
const dataset = ref<Dataset | null>(null)
const results = ref<CaseResult[]>([])
const events = ref<RunEvent[]>([])
const selectedResult = ref<CaseResult | null>(null)
const loading = ref(true)
const actionLoading = ref(false)
let pollTimer: number | undefined

const selectedCase = computed(() =>
  dataset.value?.cases?.find((item) => item.id === selectedResult.value?.case_id),
)
const isDemo = computed(() =>
  String((run.value?.manifest.dataset as Record<string, unknown> | undefined)?.name ?? '').includes(
    'demo',
  ),
)
const tokenTotal = computed(() => {
  const usage = selectedResult.value?.usage
  if (!usage) return null
  const values = [
    usage.input_tokens,
    usage.output_tokens,
    usage.cache_read_tokens,
    usage.cache_write_tokens,
    usage.reasoning_tokens,
    usage.embedding_tokens,
    usage.vision_tokens,
    usage.judge_tokens,
  ]
  return values.every((value) => value == null)
    ? null
    : values.reduce<number>((sum, value) => sum + (value ?? 0), 0)
})
const canCancel = computed(() =>
  run.value ? ['queued', 'running', 'cancel_requested'].includes(run.value.status) : false,
)
const canReplay = computed(() =>
  results.value.some((item) => item.version_role === 'candidate' && item.failure_type),
)
const hasBaseline = computed(() => run.value?.baseline_version_id != null)
const scenarioManifest = computed(() => {
  const value = run.value?.manifest.scenario
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null
})
const scenarioEvents = computed(() =>
  events.value.filter((event) => event.event_type.startsWith('scenario.')),
)

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const runRow = await api.run(runId)
    run.value = runRow
    const [datasetRow, resultRows, eventRows] = await Promise.all([
      api.dataset(runRow.dataset_id),
      api.results(runId),
      api.events(runId),
    ])
    dataset.value = datasetRow
    results.value = resultRows
    events.value = eventRows
    if (!selectedResult.value || !resultRows.some((item) => item.id === selectedResult.value?.id)) {
      selectedResult.value = resultRows.find((item) => item.failure_type) ?? resultRows[0] ?? null
    }
    if (['completed', 'cancelled', 'failed'].includes(runRow.status) && pollTimer) {
      window.clearInterval(pollTimer)
      pollTimer = undefined
    }
  } catch (error) {
    if (!silent) ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
}

async function cancel() {
  await ElMessageBox.confirm('取消后，排队运行会立即终止；运行中的当前 case 批次会协作式结束。', '取消评测运行', { type: 'warning' })
  actionLoading.value = true
  try {
    run.value = await api.cancelRun(runId)
    ElMessage.success('取消请求已记录')
    await load(true)
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    actionLoading.value = false
  }
}

async function replay() {
  actionLoading.value = true
  try {
    const replayRun = await api.replayRun(runId)
    ElMessage.success(`失败 case 已创建回放 Run #${replayRun.id}`)
    await router.push(`/runs/${replayRun.id}`)
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    actionLoading.value = false
  }
}

onMounted(async () => {
  await load()
  if (run.value && !['completed', 'cancelled', 'failed'].includes(run.value.status)) {
    pollTimer = window.setInterval(() => load(true), 1500)
  }
})
onBeforeUnmount(() => pollTimer && window.clearInterval(pollTimer))
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-header">
      <div>
        <ElButton link @click="router.push('/runs')"><ArrowLeft :size="14" /> 返回运行列表</ElButton>
        <h1 class="page-title run-title">评测运行 #{{ runId }}</h1>
        <p class="page-subtitle">{{ dataset?.name ?? '加载中' }} · {{ run ? formatDate(run.created_at) : '' }}</p>
      </div>
      <div class="page-actions">
        <ElButton @click="load()"><RefreshCw :size="15" /> 刷新</ElButton>
        <ElButton v-if="canReplay" :loading="actionLoading" @click="replay"><RotateCcw :size="15" /> 回放失败 Case</ElButton>
        <ElButton v-if="canCancel" type="danger" plain :loading="actionLoading" @click="cancel"><Square :size="14" /> 取消运行</ElButton>
        <ElButton v-if="run?.status === 'completed' && hasBaseline" @click="router.push(`/runs/${runId}/comparison`)">版本对比</ElButton>
        <ElButton v-if="run?.status === 'completed' && hasBaseline" type="primary" @click="router.push(`/runs/${runId}/gate`)">查看门禁</ElButton>
      </div>
    </div>

    <div v-if="isDemo" class="demo-banner"><strong>Demo Fixture</strong><span>该运行使用明确标记的合成评测样例，不代表真实系统评测结论。</span></div>
    <div v-else-if="run && !hasBaseline" class="demo-banner characterization-banner"><strong>Candidate-only</strong><span>这是特征评测；没有合法 Baseline，因此不会产生版本对比或发布门禁。</span></div>

    <div class="metric-strip">
      <div class="metric"><div class="metric-label">运行状态</div><div class="metric-value metric-tag"><StatusTag v-if="run" :value="run.status" /></div><div class="metric-detail">Worker 批量领取 EvalRun</div></div>
      <div class="metric"><div class="metric-label">Case 进度</div><div class="metric-value">{{ run?.completed_case_count ?? 0 }} / {{ run?.expected_case_count ?? 0 }}</div><div class="metric-detail">每个版本分别执行</div></div>
      <div class="metric"><div class="metric-label">结果记录</div><div class="metric-value">{{ results.length }}</div><div class="metric-detail">{{ run?.baseline_version_id ? 'Baseline + Candidate' : 'Candidate only' }}</div></div>
      <div class="metric"><div class="metric-label">持久事件</div><div class="metric-value">{{ events.length }}</div><div class="metric-detail">全部已脱敏</div></div>
    </div>

    <div class="split-view">
      <section class="panel result-list-panel">
        <div class="panel-header"><h2 class="panel-title">Case 结果</h2><span class="muted">点击行查看评分与 Trace</span></div>
        <div class="scroll-panel">
          <ElTable v-if="results.length" :data="results" row-key="id" highlight-current-row @current-change="(row: CaseResult) => selectedResult = row">
            <ElTableColumn label="Case" min-width="110"><template #default="{ row }"><strong>{{ dataset?.cases?.find((item) => item.id === row.case_id)?.external_id ?? `#${row.case_id}` }}</strong></template></ElTableColumn>
            <ElTableColumn label="版本" width="105"><template #default="{ row }"><StatusTag :value="row.version_role" /></template></ElTableColumn>
            <ElTableColumn label="评分" width="80"><template #default="{ row }"><span :class="row.scores.passed ? 'success-text' : 'danger-text'">{{ row.scores.passed ? '通过' : '失败' }}</span></template></ElTableColumn>
            <ElTableColumn label="延迟" width="90"><template #default="{ row }">{{ formatNumber(row.latency_ms, 'ms') }}</template></ElTableColumn>
          </ElTable>
          <EmptyState v-else title="尚无 Case 结果" description="运行排队或执行期间，Worker 会持续写入真实结果。" />
        </div>
      </section>

      <section class="panel detail-panel">
        <div class="panel-header"><h2 class="panel-title">Case、评分与 Trace</h2><StatusTag v-if="selectedResult" :value="selectedResult.version_role" /></div>
        <div v-if="selectedResult" class="scroll-panel detail-scroll">
          <div class="detail-summary">
            <div><span>Case</span><strong>{{ selectedCase?.external_id ?? `#${selectedResult.case_id}` }}</strong></div>
            <div><span>最终动作</span><strong>{{ selectedResult.final_action ?? 'UNKNOWN' }}</strong></div>
            <div><span>Token</span><strong>{{ formatNumber(tokenTotal) }}</strong></div>
            <div><span>模型费用</span><strong>{{ formatCost(selectedResult.usage?.model_cost) }}</strong></div>
          </div>
          <ElTabs>
            <ElTabPane label="评分规则">
              <ElTable v-if="selectedResult.scores.rules?.length" :data="selectedResult.scores.rules" size="small">
                <ElTableColumn label="规则" min-width="130"><template #default="{ row }"><span class="mono">{{ row.rule_id ?? row.id ?? row.category }}</span></template></ElTableColumn>
                <ElTableColumn prop="category" label="类型" width="110" />
                <ElTableColumn label="结果" width="80"><template #default="{ row }"><span :class="row.passed ? 'success-text' : 'danger-text'">{{ row.passed ? '通过' : '失败' }}</span></template></ElTableColumn>
                <ElTableColumn label="Critical" width="80"><template #default="{ row }">{{ row.critical ? '是' : '否' }}</template></ElTableColumn>
              </ElTable>
              <EmptyState v-else title="没有评分规则明细" />
            </ElTabPane>
            <ElTabPane label="输入与期望"><h3 class="detail-heading">输入</h3><pre class="json-block">{{ pretty(selectedCase?.input_data) }}</pre><h3 class="detail-heading">Expected</h3><pre class="json-block">{{ pretty(selectedCase?.expected) }}</pre></ElTabPane>
            <ElTabPane label="实际输出"><pre class="json-block">{{ pretty(selectedResult.output) }}</pre></ElTabPane>
            <ElTabPane label="Trace 与用量">
              <div class="trace-row"><span>Trace ID</span><strong class="mono">{{ selectedResult.trace_id ?? 'UNKNOWN' }}</strong><a v-if="selectedResult.trace_url" :href="selectedResult.trace_url" target="_blank" rel="noreferrer"><ExternalLink :size="14" /> Jaeger</a></div>
              <pre class="json-block">{{ pretty(selectedResult.usage) }}</pre>
            </ElTabPane>
            <ElTabPane label="运行事件">
              <div v-if="events.length" class="timeline">
                <div v-for="event in events" :key="event.id" class="timeline-item"><span class="timeline-dot" /><div><div class="timeline-title"><strong>{{ event.event_type }}</strong><span>{{ formatDate(event.occurred_at) }}</span></div><div class="timeline-meta">{{ event.source }} · {{ event.redacted ? '已脱敏' : '未标记脱敏' }}</div></div></div>
              </div>
              <EmptyState v-else title="暂无持久事件" />
            </ElTabPane>
            <ElTabPane v-if="scenarioManifest" label="多 Agent 场景">
              <div class="scenario-manifest">
                <div><span>Scenario SHA</span><strong class="mono">{{ String(scenarioManifest.sha256 ?? 'UNKNOWN') }}</strong></div>
                <div><span>节点数</span><strong>{{ scenarioManifest.node_count ?? 0 }}</strong></div>
                <div><span>参与 Version</span><strong>{{ Array.isArray(scenarioManifest.participant_version_ids) ? scenarioManifest.participant_version_ids.join(', ') : 'UNKNOWN' }}</strong></div>
              </div>
              <div v-if="scenarioEvents.length" class="timeline scenario-timeline">
                <div v-for="event in scenarioEvents" :key="event.id" class="timeline-item"><span class="timeline-dot" /><div><div class="timeline-title"><strong>{{ event.event_type }}</strong><span>{{ formatDate(event.occurred_at) }}</span></div><div class="timeline-meta">{{ event.payload.node_id ?? event.payload.from_node ?? 'scenario' }}<template v-if="event.payload.to_node"> → {{ event.payload.to_node }}</template></div></div></div>
              </div>
              <EmptyState v-else title="场景事件尚未写入" />
            </ElTabPane>
          </ElTabs>
        </div>
        <EmptyState v-else title="选择一个 Case 结果" description="右侧将显示输入、期望、实际输出、规则评分和 Trace。" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.run-title { margin-top: 4px; }
.metric-tag { display: flex; align-items: center; height: 28px; }
.result-list-panel, .detail-panel { min-width: 0; }
.detail-scroll { padding: 14px; }
.detail-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-bottom: 10px; overflow: hidden; border: 1px solid var(--border); border-radius: 6px; background: var(--border); }
.detail-summary > div { min-width: 0; padding: 9px 10px; background: white; }
.detail-summary span { display: block; color: var(--muted); font-size: 10px; }
.detail-summary strong { display: block; margin-top: 4px; overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.detail-heading { margin: 12px 0 6px; font-size: 12px; }
.trace-row { display: grid; grid-template-columns: 80px minmax(0, 1fr) auto; align-items: center; gap: 10px; margin-bottom: 12px; padding: 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 11px; }
.trace-row a { display: flex; align-items: center; gap: 4px; color: #1d5dcc; }
.timeline { padding: 4px 2px; }
.timeline-item { position: relative; display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 7px; min-height: 56px; }
.timeline-item::before { content: ''; position: absolute; left: 5px; top: 13px; bottom: -3px; width: 1px; background: #d9dee7; }
.timeline-item:last-child::before { display: none; }
.timeline-dot { position: relative; z-index: 1; width: 11px; height: 11px; margin-top: 3px; border: 2px solid white; border-radius: 50%; background: #3b6fd8; box-shadow: 0 0 0 1px #3b6fd8; }
.timeline-title { display: flex; justify-content: space-between; gap: 8px; font-size: 11px; }
.timeline-title span, .timeline-meta { color: var(--muted); font-size: 10px; }
.timeline-meta { margin-top: 4px; }
.characterization-banner { border-color: #b8c7df; background: #f5f8fc; color: #344054; }
.scenario-manifest { display: grid; grid-template-columns: minmax(0, 1.6fr) .5fr 1fr; gap: 1px; margin-bottom: 14px; overflow: hidden; border: 1px solid var(--border); border-radius: 6px; background: var(--border); }
.scenario-manifest > div { min-width: 0; padding: 9px 10px; background: white; }
.scenario-manifest span { display: block; color: var(--muted); font-size: 10px; }
.scenario-manifest strong { display: block; margin-top: 4px; overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.scenario-timeline { padding: 4px 8px; }
@media (max-width: 760px) { .detail-summary { grid-template-columns: 1fr 1fr; } }
</style>
