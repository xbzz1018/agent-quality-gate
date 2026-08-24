<script setup lang="ts">
import { BarChart3, Plus, RotateCcw, ShieldCheck } from '@lucide/vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '@/components/EmptyState.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api, apiError } from '@/services/api'
import { useCatalogStore } from '@/stores/catalog'
import type { EvalRun } from '@/types/api'

const route = useRoute()
const router = useRouter()
const catalog = useCatalogStore()
const runs = ref<EvalRun[]>([])
const total = ref(0)
const page = ref(1)
const statusFilter = ref('')
const targetFilter = ref<number | undefined>()
const loading = ref(true)
const dialog = ref(false)
const saving = ref(false)
const form = reactive({
  target_id: undefined as number | undefined,
  dataset_id: undefined as number | undefined,
  baseline_version_id: undefined as number | undefined,
  candidate_version_id: undefined as number | undefined,
  gate_policy_id: undefined as number | undefined,
  pricing_snapshot_id: undefined as number | undefined,
})

const targetVersions = computed(() =>
  form.target_id ? catalog.versionsByTarget[form.target_id] ?? [] : [],
)
const pageContext = computed(() => {
  if (route.query.view === 'comparison') return '选择已完成运行查看 Baseline/Candidate 指标差值'
  if (route.query.view === 'trace') return '选择运行查看 Case 结果、事件与 Trace'
  if (route.query.view === 'gate') return '选择已完成运行查看发布门禁审计'
  return '创建、跟踪和审计 Inspect AI 批量评测'
})

watch(
  () => form.target_id,
  () => {
    form.baseline_version_id = undefined
    form.candidate_version_id = undefined
  },
)

async function load() {
  loading.value = true
  try {
    await catalog.refresh()
    const result = await api.runs({
      page: page.value,
      page_size: 20,
      status: statusFilter.value || undefined,
      target_id: targetFilter.value,
    })
    runs.value = result.items
    total.value = result.total
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
}

function openRun(run: EvalRun) {
  if (route.query.view === 'comparison') router.push(`/runs/${run.id}/comparison`)
  else if (route.query.view === 'gate') router.push(`/runs/${run.id}/gate`)
  else router.push(`/runs/${run.id}`)
}

async function createRun() {
  saving.value = true
  try {
    const run = await api.createRun({
      dataset_id: form.dataset_id,
      baseline_version_id: form.baseline_version_id,
      candidate_version_id: form.candidate_version_id,
      gate_policy_id: form.gate_policy_id,
      pricing_snapshot_id: form.pricing_snapshot_id,
      benchmark_mode: false,
      config: { source: 'web-console' },
    })
    ElMessage.success(`Run #${run.id} 已进入队列`)
    dialog.value = false
    await router.push(`/runs/${run.id}`)
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

function versionLabel(id: number | null) {
  if (id === null) return '未设置'
  const version = catalog.versions.find((item) => item.id === id)
  return version?.version ?? `#${id}`
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div><h1 class="page-title">评测运行</h1><p class="page-subtitle">{{ pageContext }}</p></div>
      <div class="page-actions"><ElButton @click="load"><RotateCcw :size="15" /> 刷新</ElButton><ElButton type="primary" @click="dialog = true"><Plus :size="15" /> 创建运行</ElButton></div>
    </div>
    <div class="filters-band">
      <ElSelect v-model="statusFilter" clearable placeholder="全部状态" style="width: 160px" @change="load">
        <ElOption label="Queued" value="queued" /><ElOption label="Running" value="running" /><ElOption label="Completed" value="completed" /><ElOption label="Failed" value="failed" /><ElOption label="Cancelled" value="cancelled" />
      </ElSelect>
      <ElSelect v-model="targetFilter" clearable filterable placeholder="全部目标" style="width: 220px" @change="load">
        <ElOption v-for="target in catalog.targets" :key="target.id" :label="target.name" :value="target.id" />
      </ElSelect>
    </div>
    <section class="panel">
      <ElTable v-if="runs.length" v-loading="loading" :data="runs" row-key="id" @row-click="openRun">
        <ElTableColumn label="Run" width="90"><template #default="{ row }"><a class="table-link">#{{ row.id }}</a></template></ElTableColumn>
        <ElTableColumn label="状态" width="110"><template #default="{ row }"><StatusTag :value="row.status" /></template></ElTableColumn>
        <ElTableColumn label="Baseline" min-width="125"><template #default="{ row }"><span v-if="row.baseline_version_id">{{ versionLabel(row.baseline_version_id) }}</span><ElTag v-else size="small" type="info">特征评测</ElTag></template></ElTableColumn>
        <ElTableColumn label="Candidate" min-width="125"><template #default="{ row }"><strong>{{ versionLabel(row.candidate_version_id) }}</strong></template></ElTableColumn>
        <ElTableColumn label="Cases" width="110"><template #default="{ row }">{{ row.completed_case_count }} / {{ row.expected_case_count }}</template></ElTableColumn>
        <ElTableColumn label="来源" width="120"><template #default="{ row }"><ElTag v-if="row.manifest?.dataset?.name?.includes('demo')" type="warning" size="small">Demo Fixture</ElTag><span v-else>真实配置</span></template></ElTableColumn>
        <ElTableColumn label="创建时间" min-width="180"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template></ElTableColumn>
        <ElTableColumn label="查看" width="110" fixed="right"><template #default="{ row }"><BarChart3 v-if="route.query.view === 'comparison'" :size="16" /><ShieldCheck v-else-if="route.query.view === 'gate'" :size="16" /><span v-else>详情</span></template></ElTableColumn>
      </ElTable>
      <EmptyState v-else title="暂无评测运行" description="先创建目标版本和冻结数据集，然后发起 Baseline/Candidate 对比。" />
      <div v-if="total > 20" class="pagination-row"><ElPagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next, total" @current-change="load" /></div>
    </section>

    <ElDialog v-model="dialog" title="创建评测运行" width="600px">
      <ElForm label-position="top">
        <ElFormItem label="被测目标" required><ElSelect v-model="form.target_id" filterable placeholder="选择目标"><ElOption v-for="target in catalog.targets" :key="target.id" :label="target.name" :value="target.id" /></ElSelect></ElFormItem>
        <ElFormItem label="冻结数据集" required><ElSelect v-model="form.dataset_id" filterable placeholder="选择数据集"><ElOption v-for="dataset in catalog.datasets" :key="dataset.id" :label="`${dataset.name} · ${dataset.version} · ${dataset.case_count} cases`" :value="dataset.id" /></ElSelect></ElFormItem>
        <div class="form-grid"><ElFormItem label="Baseline（可选）"><ElSelect v-model="form.baseline_version_id" clearable placeholder="留空为特征评测"><ElOption v-for="version in targetVersions" :key="version.id" :label="version.version" :value="version.id" :disabled="version.id === form.candidate_version_id" /></ElSelect></ElFormItem><ElFormItem label="Candidate" required><ElSelect v-model="form.candidate_version_id" placeholder="选择版本"><ElOption v-for="version in targetVersions" :key="version.id" :label="version.version" :value="version.id" :disabled="version.id === form.baseline_version_id" /></ElSelect></ElFormItem></div>
        <div class="form-grid"><ElFormItem label="Gate Policy"><ElSelect v-model="form.gate_policy_id" clearable placeholder="使用当前 active policy"><ElOption v-for="policy in catalog.policies" :key="policy.id" :label="`${policy.name} · ${policy.version}`" :value="policy.id" /></ElSelect></ElFormItem><ElFormItem label="Pricing Snapshot"><ElSelect v-model="form.pricing_snapshot_id" clearable placeholder="未知费用"><ElOption v-for="item in catalog.pricing" :key="item.id" :label="`${item.provider}/${item.model} · ${item.version}`" :value="item.id" /></ElSelect></ElFormItem></div>
      </ElForm>
      <template #footer><ElButton @click="dialog = false">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="!form.dataset_id || !form.candidate_version_id" @click="createRun">进入评测队列</ElButton></template>
    </ElDialog>
  </div>
</template>

<style scoped>
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
:deep(.el-table__row) { cursor: pointer; }
@media (max-width: 620px) { .form-grid { grid-template-columns: 1fr; } }
</style>
