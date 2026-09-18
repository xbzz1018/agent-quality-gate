<script setup lang="ts">
import { Ban, CheckCircle2, Plus, RefreshCw, Workflow } from '@lucide/vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import EmptyState from '@/components/EmptyState.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api, apiError } from '@/services/api'
import type { AgentVersion, ScenarioMode, ScenarioRun, Target } from '@/types/api'
import { formatDate, formatNumber, pretty } from '@/utils/format'

const activeTab = ref('runs')
const runs = ref<ScenarioRun[]>([])
const scenarios = ref<Target[]>([])
const versions = ref<AgentVersion[]>([])
const selectedRun = ref<ScenarioRun | null>(null)
const loading = ref(false)
const saving = ref(false)
const statusFilter = ref('')
const modeFilter = ref('')
const targetDialog = ref(false)
const versionDialog = ref(false)
const runDialog = ref(false)
const selectedTarget = ref<Target | null>(null)
const compactMedia = window.matchMedia('(max-width: 620px)')
const compactViewport = ref(compactMedia.matches)
const targetForm = reactive({ name: '' })
const versionForm = reactive({ version: '', graph: '' })
const runForm = reactive({
  scenario_version_id: undefined as number | undefined,
  mode: 'shadow' as ScenarioMode,
  input: '{\n  "question": ""\n}',
  max_total_tokens: 10000 as number | undefined,
  max_cost_usd: undefined as number | undefined,
})

const scenarioVersions = computed(() =>
  versions.value.filter((version) => scenarios.value.some((item) => item.id === version.target_id)),
)

async function load() {
  loading.value = true
  try {
    const [runPage, targetPage] = await Promise.all([
      api.scenarioRuns({
        page: 1,
        page_size: 50,
        run_status: statusFilter.value || undefined,
        mode: modeFilter.value || undefined,
      }),
      api.targets({ protocol: 'scenario', page: 1, page_size: 100 }),
    ])
    runs.value = runPage.items
    scenarios.value = targetPage.items
    const loaded = await Promise.all(scenarios.value.map((item) => api.versions(item.id)))
    versions.value = loaded.flat()
    if (selectedRun.value) {
      selectedRun.value = runs.value.find((item) => item.id === selectedRun.value?.id) ?? null
    }
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
}

async function openRun(row: ScenarioRun) {
  try {
    selectedRun.value = await api.scenarioRun(row.id)
  } catch (error) {
    ElMessage.error(apiError(error))
  }
}

async function createTarget() {
  saving.value = true
  try {
    await api.createTarget({
      name: targetForm.name,
      target_kind: 'scenario',
      protocol: 'scenario',
      endpoint: 'internal://scenario',
      timeout_seconds: 180,
      capabilities: { contract_profile: 'multi_agent_scenario_v1' },
    })
    targetDialog.value = false
    targetForm.name = ''
    ElMessage.success('Scenario Target 已创建')
    await load()
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

function openVersion(target: Target) {
  selectedTarget.value = target
  versionForm.version = ''
  versionForm.graph = JSON.stringify(
    {
      schema: 'aqh.scenario/v1',
      nodes: [],
      output: '$nodes.final.output',
      limits: { max_parallel_nodes: 4, timeout_seconds: 180 },
    },
    null,
    2,
  )
  versionDialog.value = true
}

async function createVersion() {
  if (!selectedTarget.value) return
  saving.value = true
  try {
    const graph = JSON.parse(versionForm.graph)
    const version = await api.createVersion(selectedTarget.value.id, {
      version: versionForm.version,
      metadata: { scenario: graph },
    })
    const validation = await api.validateScenarioVersion(version.id)
    versionDialog.value = false
    ElMessage.success(`Scenario Version 已冻结 · ${validation.sha256.slice(0, 12)}`)
    await load()
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

async function createRun() {
  saving.value = true
  try {
    const input = JSON.parse(runForm.input)
    const run = await api.createScenarioRun({
      scenario_version_id: runForm.scenario_version_id,
      mode: runForm.mode,
      input,
      limits: {
        max_total_tokens: runForm.max_total_tokens,
        max_cost_usd: runForm.max_cost_usd,
      },
    })
    runDialog.value = false
    ElMessage.success(`Scenario Run #${run.id} 已进入队列`)
    await load()
    await openRun(run)
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

async function cancelRun() {
  if (!selectedRun.value) return
  await ElMessageBox.confirm('取消请求会停止后续节点并关闭活动调用。', '取消 Scenario Run', {
    type: 'warning',
  })
  try {
    selectedRun.value = await api.cancelScenarioRun(selectedRun.value.id)
    ElMessage.success('取消请求已记录')
    await load()
  } catch (error) {
    ElMessage.error(apiError(error))
  }
}

function versionLabel(id: number) {
  const version = versions.value.find((item) => item.id === id)
  const target = scenarios.value.find((item) => item.id === version?.target_id)
  return version ? `${target?.name ?? `Target #${version.target_id}`} · ${version.version}` : `#${id}`
}

function updateCompactViewport(event: MediaQueryListEvent) {
  compactViewport.value = event.matches
}

onMounted(() => {
  compactMedia.addEventListener('change', updateCompactViewport)
  void load()
})
onBeforeUnmount(() => compactMedia.removeEventListener('change', updateCompactViewport))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">场景运行</h1>
        <p class="page-subtitle">冻结多 Agent DAG、Shadow 验证与 Gate 授权 Pilot</p>
      </div>
      <div class="page-actions">
        <ElButton @click="load"><RefreshCw :size="15" /> 刷新</ElButton>
        <ElButton @click="targetDialog = true"><Plus :size="15" /> 新建场景</ElButton>
        <ElButton type="primary" :disabled="!scenarioVersions.length" @click="runDialog = true">
          <Workflow :size="15" /> 发起运行
        </ElButton>
      </div>
    </div>

    <ElTabs v-model="activeTab" class="admin-tabs">
      <ElTabPane label="运行控制" name="runs" />
      <ElTabPane label="场景版本" name="definitions" />
    </ElTabs>

    <template v-if="activeTab === 'runs'">
      <div class="filters-band">
        <ElSelect v-model="statusFilter" clearable placeholder="全部状态" style="width: 150px" @change="load">
          <ElOption label="Queued" value="queued" /><ElOption label="Running" value="running" />
          <ElOption label="Completed" value="completed" /><ElOption label="Failed" value="failed" />
          <ElOption label="Cancelled" value="cancelled" />
        </ElSelect>
        <ElSegmented v-model="modeFilter" :options="[{ label: '全部模式', value: '' }, { label: 'Shadow', value: 'shadow' }, { label: 'Pilot', value: 'pilot' }]" @change="load" />
      </div>
      <div class="split-view scenario-split">
        <section class="panel">
          <div class="panel-header"><h2 class="panel-title">Scenario Runs</h2><span class="muted">{{ runs.length }} 条</span></div>
          <ElTable v-if="runs.length" v-loading="loading" :data="runs" row-key="id" highlight-current-row @current-change="openRun">
            <ElTableColumn label="Run" width="80"><template #default="{ row }"><span class="table-link">#{{ row.id }}</span></template></ElTableColumn>
            <ElTableColumn label="模式" width="90"><template #default="{ row }"><StatusTag :value="row.mode" /></template></ElTableColumn>
            <ElTableColumn label="状态" width="100"><template #default="{ row }"><StatusTag :value="row.status" /></template></ElTableColumn>
            <ElTableColumn v-if="!compactViewport" label="场景版本" min-width="180"><template #default="{ row }">{{ versionLabel(row.scenario_version_id) }}</template></ElTableColumn>
            <ElTableColumn v-if="!compactViewport" label="创建时间" min-width="150"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></ElTableColumn>
          </ElTable>
          <EmptyState v-else title="暂无 Scenario Run" description="先冻结一个场景版本，再执行 Shadow 或 Gate 授权 Pilot。" />
        </section>
        <section class="panel detail-panel">
          <div class="panel-header">
            <h2 class="panel-title">节点检查器</h2>
            <ElButton v-if="selectedRun && ['queued', 'running', 'cancel_requested'].includes(selectedRun.status)" link type="danger" @click="cancelRun"><Ban :size="14" /> 取消</ElButton>
          </div>
          <div v-if="selectedRun" class="scenario-inspector">
            <div class="detail-summary scenario-summary">
              <div><span>运行</span><strong>#{{ selectedRun.id }}</strong></div>
              <div><span>状态</span><StatusTag :value="selectedRun.status" /></div>
              <div><span>Trace</span><strong class="mono">{{ selectedRun.trace_id?.slice(0, 12) ?? 'UNKNOWN' }}</strong></div>
              <div><span>尝试</span><strong>{{ selectedRun.attempt }}</strong></div>
            </div>
            <div v-if="selectedRun.nodes.length" class="node-list">
              <div v-for="node in selectedRun.nodes" :key="`${node.node_id}-${node.attempt}`" class="node-row">
                <span class="node-state" :class="`node-state--${node.status}`"><CheckCircle2 :size="14" /></span>
                <div><strong>{{ node.node_id }}</strong><small>Version #{{ node.target_version_id }} · {{ formatNumber(node.latency_ms, 'ms') }}</small></div>
                <StatusTag :value="node.status" />
              </div>
            </div>
            <EmptyState v-else title="节点尚未执行" />
            <ElTabs>
              <ElTabPane label="输出"><pre class="json-block">{{ pretty(selectedRun.output) }}</pre></ElTabPane>
              <ElTabPane label="用量"><pre class="json-block">{{ pretty(selectedRun.usage) }}</pre></ElTabPane>
              <ElTabPane label="限制"><pre class="json-block">{{ pretty(selectedRun.limits) }}</pre></ElTabPane>
            </ElTabs>
          </div>
          <EmptyState v-else title="选择一个 Scenario Run" description="查看节点状态、用量、输出和 Trace。" />
        </section>
      </div>
    </template>

    <section v-else class="panel">
      <ElTable v-if="scenarios.length" :data="scenarios" row-key="id">
        <ElTableColumn prop="name" label="Scenario Target" min-width="220" />
        <ElTableColumn label="协议" width="110"><template #default="{ row }"><StatusTag :value="row.protocol" /></template></ElTableColumn>
        <ElTableColumn label="版本" width="100"><template #default="{ row }">{{ versions.filter((item) => item.target_id === row.id).length }}</template></ElTableColumn>
        <ElTableColumn prop="endpoint" label="Endpoint" min-width="200" />
        <ElTableColumn label="操作" width="120"><template #default="{ row }"><ElButton link type="primary" @click="openVersion(row)">冻结版本</ElButton></template></ElTableColumn>
      </ElTable>
      <EmptyState v-else title="暂无 Scenario Target" />
    </section>

    <ElDialog v-model="targetDialog" title="新建 Scenario Target" width="500px">
      <ElForm label-position="top"><ElFormItem label="名称" required><ElInput v-model="targetForm.name" /></ElFormItem></ElForm>
      <template #footer><ElButton @click="targetDialog = false">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="!targetForm.name" @click="createTarget">创建</ElButton></template>
    </ElDialog>

    <ElDialog v-model="versionDialog" :title="`冻结版本 · ${selectedTarget?.name ?? ''}`" width="720px">
      <ElForm label-position="top">
        <ElFormItem label="版本标识" required><ElInput v-model="versionForm.version" /></ElFormItem>
        <ElFormItem label="aqh.scenario/v1 Graph" required><ElInput v-model="versionForm.graph" type="textarea" :rows="18" class="graph-editor" /></ElFormItem>
      </ElForm>
      <template #footer><ElButton @click="versionDialog = false">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="!versionForm.version" @click="createVersion">校验并冻结</ElButton></template>
    </ElDialog>

    <ElDialog v-model="runDialog" title="发起 Scenario Run" width="600px">
      <ElForm label-position="top">
        <ElFormItem label="场景版本" required><ElSelect v-model="runForm.scenario_version_id" filterable><ElOption v-for="version in scenarioVersions" :key="version.id" :label="versionLabel(version.id)" :value="version.id" /></ElSelect></ElFormItem>
        <ElFormItem label="模式"><ElSegmented v-model="runForm.mode" :options="[{ label: 'Shadow', value: 'shadow' }, { label: 'Pilot', value: 'pilot' }]" /></ElFormItem>
        <ElFormItem label="输入 JSON" required><ElInput v-model="runForm.input" type="textarea" :rows="7" class="graph-editor" /></ElFormItem>
        <div class="form-grid"><ElFormItem label="最大 Token"><ElInputNumber v-model="runForm.max_total_tokens" :min="1" /></ElFormItem><ElFormItem label="最大费用 USD"><ElInputNumber v-model="runForm.max_cost_usd" :min="0.000001" :precision="6" /></ElFormItem></div>
      </ElForm>
      <template #footer><ElButton @click="runDialog = false">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="!runForm.scenario_version_id" @click="createRun">进入队列</ElButton></template>
    </ElDialog>
  </div>
</template>

<style scoped>
.scenario-split { grid-template-columns: minmax(540px, 1.1fr) minmax(420px, .9fr); }
.scenario-split > .panel { min-width: 0; }
.scenario-inspector { padding: 14px; }
.scenario-summary { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.node-list { display: grid; gap: 8px; margin-bottom: 14px; }
.node-row { min-height: 58px; display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; align-items: center; gap: 9px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 7px; }
.node-row > div { min-width: 0; display: grid; gap: 3px; }
.node-row small { overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.node-state { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 50%; color: #667085; background: #f2f4f7; }
.node-state--completed { color: var(--success); background: #eaf8f1; }
.node-state--failed { color: var(--danger); background: #fff0f0; }
.graph-editor :deep(textarea) { font-family: "Cascadia Code", Consolas, monospace; font-size: 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 1050px) { .scenario-split { grid-template-columns: 1fr; } }
@media (max-width: 620px) {
  .scenario-summary, .form-grid { grid-template-columns: 1fr 1fr; }
}
</style>
