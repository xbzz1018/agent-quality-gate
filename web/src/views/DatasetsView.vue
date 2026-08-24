<script setup lang="ts">
import { FileJson, Upload } from '@lucide/vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { onMounted, ref } from 'vue'

import EmptyState from '@/components/EmptyState.vue'
import { api, apiError } from '@/services/api'
import { useCatalogStore } from '@/stores/catalog'
import type { Dataset } from '@/types/api'

const catalog = useCatalogStore()
const dialog = ref(false)
const saving = ref(false)
const filename = ref('')
const document = ref<Record<string, unknown> | null>(null)
const isDemo = ref(false)
const rows = ref<Dataset[]>([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const versionFilter = ref('')
const preview = ref<Dataset | null>(null)

async function load() {
  const result = await api.datasets({
    search: search.value || undefined,
    version: versionFilter.value || undefined,
    page: page.value,
    page_size: 20,
  })
  rows.value = result.items
  total.value = result.total
}

async function openPreview(row: Dataset) {
  preview.value = await api.dataset(row.id)
}

async function selectFile(file: UploadFile) {
  if (!file.raw) return
  try {
    const parsed = JSON.parse(await file.raw.text()) as Record<string, unknown>
    if (!Array.isArray(parsed.cases) || !parsed.name || !parsed.version) {
      throw new Error('文件必须包含 name、version 和 cases')
    }
    document.value = parsed
    filename.value = file.name
    isDemo.value = parsed.demo_fixture === true
  } catch (error) {
    document.value = null
    ElMessage.error(apiError(error))
  }
}

async function importDataset() {
  if (!document.value) return
  saving.value = true
  try {
    await api.importDataset(document.value)
    ElMessage.success('数据集已冻结导入')
    dialog.value = false
    document.value = null
    await catalog.refresh()
    await load()
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

onMounted(() => Promise.all([catalog.refresh(), load()]).catch((error) => ElMessage.error(apiError(error))))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div><h1 class="page-title">评测数据集</h1><p class="page-subtitle">哈希冻结的 Eval Case 与确定性 expected 规则</p></div>
      <ElButton type="primary" @click="dialog = true"><Upload :size="15" /> 导入 JSON</ElButton>
    </div>
    <div class="filters-band">
      <ElInput v-model="search" clearable placeholder="搜索数据集" style="width: 260px" @keyup.enter="load" />
      <ElInput v-model="versionFilter" clearable placeholder="版本" style="width: 150px" @keyup.enter="load" />
      <ElButton @click="load">查询</ElButton>
    </div>
    <section class="panel">
      <ElTable v-if="rows.length" v-loading="catalog.loading" :data="rows" row-key="id" @row-click="openPreview">
        <ElTableColumn prop="name" label="数据集" min-width="230"><template #default="{ row }"><a class="table-link">{{ row.name }}</a><ElTag v-if="row.name.includes('demo')" type="warning" size="small" class="demo-inline">Demo Fixture</ElTag></template></ElTableColumn>
        <ElTableColumn prop="version" label="版本" width="100" />
        <ElTableColumn prop="split" label="Split" width="90" />
        <ElTableColumn prop="case_count" label="Cases" width="90" />
        <ElTableColumn label="SHA-256" min-width="240"><template #default="{ row }"><span class="mono">{{ row.sha256.slice(0, 18) }}…</span></template></ElTableColumn>
        <ElTableColumn label="冻结时间" min-width="180"><template #default="{ row }">{{ new Date(row.frozen_at).toLocaleString('zh-CN') }}</template></ElTableColumn>
      </ElTable>
      <EmptyState v-else title="暂无冻结数据集" description="导入符合 expected 规则结构的 JSON 文件。" />
      <div v-if="total > 20" class="pagination-row"><ElPagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next, total" @current-change="load" /></div>
    </section>

    <ElDialog v-model="dialog" title="导入冻结数据集" width="560px">
      <ElUpload drag accept="application/json,.json" :auto-upload="false" :limit="1" :on-change="selectFile">
        <FileJson :size="30" />
        <div class="upload-title">选择或拖入 JSON 文件</div>
        <div class="muted upload-hint">文件由 API 校验规则结构并计算 SHA-256</div>
      </ElUpload>
      <div v-if="filename" class="file-summary"><strong>{{ filename }}</strong><ElTag v-if="isDemo" type="warning" size="small">Demo Fixture</ElTag></div>
      <template #footer><ElButton @click="dialog = false">取消</ElButton><ElButton type="primary" :disabled="!document" :loading="saving" @click="importDataset">导入并冻结</ElButton></template>
    </ElDialog>
    <ElDrawer :model-value="preview !== null" title="Eval Case 预览" size="min(720px, 92vw)" @close="preview = null">
      <div v-if="preview" class="section-stack">
        <div class="dataset-meta"><strong>{{ preview.name }} · {{ preview.version }}</strong><span class="mono">{{ preview.sha256 }}</span></div>
        <div v-for="item in preview.cases?.slice(0, 20)" :key="item.id" class="case-preview">
          <div><strong>{{ item.external_id }}</strong><span>{{ item.tags.join(' · ') || '无标签' }}</span></div>
          <pre class="json-block">{{ JSON.stringify({ input: item.input_data, expected: item.expected }, null, 2) }}</pre>
        </div>
      </div>
    </ElDrawer>
  </div>
</template>

<style scoped>
.demo-inline { margin-left: 8px; }
.upload-title { margin-top: 9px; font-size: 13px; font-weight: 650; }
.upload-hint { margin-top: 4px; font-size: 11px; }
.file-summary { margin-top: 12px; display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; }
.dataset-meta { display: grid; gap: 6px; }
.dataset-meta span { overflow-wrap: anywhere; color: var(--muted); }
.case-preview { padding-bottom: 14px; border-bottom: 1px solid var(--border); }
.case-preview > div { margin-bottom: 8px; display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
</style>
