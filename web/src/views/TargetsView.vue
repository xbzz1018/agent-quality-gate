<script setup lang="ts">
import { FlaskConical, Plus } from '@lucide/vue'
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import EmptyState from '@/components/EmptyState.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api, apiError } from '@/services/api'
import { useCatalogStore } from '@/stores/catalog'
import type { Target } from '@/types/api'

const catalog = useCatalogStore()
const targetDialog = ref(false)
const versionDialog = ref(false)
const saving = ref(false)
const selectedTarget = ref<Target | null>(null)
const targetForm = reactive({ name: '', protocol: 'http', endpoint: '', timeout_seconds: 30 })
const versionForm = reactive({ version: '', model: '', prompt_version: '' })
const rows = ref<Target[]>([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const protocolFilter = ref('')

async function load() {
  await catalog.refresh()
  const result = await api.targets({
    search: search.value || undefined,
    protocol: protocolFilter.value || undefined,
    page: page.value,
    page_size: 20,
  })
  rows.value = result.items
  total.value = result.total
  const versions = await Promise.all(
    rows.value.map(async (target) => [target.id, await api.versions(target.id)] as const),
  )
  Object.assign(catalog.versionsByTarget, Object.fromEntries(versions))
}

async function createTarget() {
  saving.value = true
  try {
    await api.createTarget({
      ...targetForm,
      target_kind: targetForm.protocol === 'mcp' ? 'tool' : 'agent',
      capabilities: {},
    })
    ElMessage.success('被测目标已创建')
    targetDialog.value = false
    Object.assign(targetForm, { name: '', protocol: 'http', endpoint: '', timeout_seconds: 30 })
    await load()
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

function openVersion(target: Target) {
  selectedTarget.value = target
  Object.assign(versionForm, { version: '', model: '', prompt_version: '' })
  versionDialog.value = true
}

async function createVersion() {
  if (!selectedTarget.value) return
  saving.value = true
  try {
    await api.createVersion(selectedTarget.value.id, { ...versionForm, metadata: {} })
    ElMessage.success('目标版本已创建')
    versionDialog.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

async function bootstrap() {
  saving.value = true
  try {
    const result = await api.bootstrapDemo()
    ElMessage.success(result.created_resources.length ? 'Demo Fixture 已初始化' : 'Demo Fixture 已存在')
    await load()
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

onMounted(() => load().catch((error) => ElMessage.error(apiError(error))))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div><h1 class="page-title">被测目标</h1><p class="page-subtitle">Agent 协议连接与可复现版本快照</p></div>
      <div class="page-actions">
        <ElButton :loading="saving" @click="bootstrap"><FlaskConical :size="15" /> Demo Fixture</ElButton>
        <ElButton type="primary" @click="targetDialog = true"><Plus :size="15" /> 新建目标</ElButton>
      </div>
    </div>
    <div class="filters-band">
      <ElInput v-model="search" clearable placeholder="搜索目标名称" style="width: 260px" @keyup.enter="load" />
      <ElSelect v-model="protocolFilter" clearable placeholder="全部协议" style="width: 150px" @change="load"><ElOption label="HTTP" value="http" /><ElOption label="SSE" value="sse" /><ElOption label="AG-UI" value="ag_ui" /><ElOption label="A2A" value="a2a" /><ElOption label="MCP" value="mcp" /></ElSelect>
      <ElButton @click="load">查询</ElButton>
    </div>

    <section class="panel">
      <ElTable v-if="rows.length" v-loading="catalog.loading" :data="rows" row-key="id">
        <ElTableColumn prop="name" label="目标" min-width="180">
          <template #default="{ row }"><strong>{{ row.name }}</strong><ElTag v-if="row.capabilities.demo_fixture" class="demo-inline" type="warning" size="small">Demo Fixture</ElTag></template>
        </ElTableColumn>
        <ElTableColumn label="协议" width="100"><template #default="{ row }"><StatusTag :value="row.protocol" /></template></ElTableColumn>
        <ElTableColumn prop="endpoint" label="Endpoint" min-width="260" show-overflow-tooltip />
        <ElTableColumn label="版本" width="90"><template #default="{ row }">{{ catalog.versionsByTarget[row.id]?.length ?? 0 }}</template></ElTableColumn>
        <ElTableColumn label="状态" width="90"><template #default="{ row }"><span :class="row.enabled ? 'success-text' : 'muted'">{{ row.enabled ? '启用' : '停用' }}</span></template></ElTableColumn>
        <ElTableColumn label="操作" width="120" fixed="right"><template #default="{ row }"><ElButton link type="primary" @click="openVersion(row)">添加版本</ElButton></template></ElTableColumn>
      </ElTable>
      <EmptyState v-else title="暂无被测目标" description="登记 HTTP/SSE/A2A Agent 或 MCP Tool，或初始化明确标记的 Demo Fixture。" />
      <div v-if="total > 20" class="pagination-row"><ElPagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next, total" @current-change="load" /></div>
    </section>

    <ElDialog v-model="targetDialog" title="新建被测目标" width="520px">
      <ElForm label-position="top">
        <ElFormItem label="名称" required><ElInput v-model="targetForm.name" /></ElFormItem>
        <div class="form-grid"><ElFormItem label="协议" required><ElSelect v-model="targetForm.protocol"><ElOption label="HTTP" value="http" /><ElOption label="SSE" value="sse" /><ElOption label="AG-UI" value="ag_ui" /><ElOption label="A2A" value="a2a" /><ElOption label="MCP" value="mcp" /></ElSelect></ElFormItem><ElFormItem label="超时（秒）"><ElInputNumber v-model="targetForm.timeout_seconds" :min="1" :max="600" /></ElFormItem></div>
        <ElFormItem label="Endpoint" required><ElInput v-model="targetForm.endpoint" placeholder="http://127.0.0.1:8020/invoke" /></ElFormItem>
      </ElForm>
      <template #footer><ElButton @click="targetDialog = false">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="!targetForm.name || !targetForm.endpoint" @click="createTarget">创建</ElButton></template>
    </ElDialog>

    <ElDialog v-model="versionDialog" :title="`添加版本 · ${selectedTarget?.name ?? ''}`" width="520px">
      <ElForm label-position="top">
        <ElFormItem label="版本标识" required><ElInput v-model="versionForm.version" placeholder="candidate-2026.08" /></ElFormItem>
        <div class="form-grid"><ElFormItem label="模型"><ElInput v-model="versionForm.model" /></ElFormItem><ElFormItem label="Prompt 版本"><ElInput v-model="versionForm.prompt_version" /></ElFormItem></div>
      </ElForm>
      <template #footer><ElButton @click="versionDialog = false">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="!versionForm.version" @click="createVersion">创建</ElButton></template>
    </ElDialog>
  </div>
</template>

<style scoped>
.demo-inline { margin-left: 8px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 600px) { .form-grid { grid-template-columns: 1fr; } }
</style>
