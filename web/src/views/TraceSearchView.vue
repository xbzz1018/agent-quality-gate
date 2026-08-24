<script setup lang="ts">
import { Search } from '@lucide/vue'
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import EmptyState from '@/components/EmptyState.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api, apiError } from '@/services/api'
import type { CaseResult } from '@/types/api'

const router = useRouter()
const rows = ref<CaseResult[]>([])
const total = ref(0)
const loading = ref(false)
const failureOnly = ref(true)
const traceId = ref('')
const runId = ref<number | undefined>()
const page = ref(1)

async function load() {
  loading.value = true
  try {
    const result = await api.searchResults({
      failure_only: failureOnly.value,
      trace_id: traceId.value || undefined,
      run_id: runId.value,
      page: page.value,
      page_size: 20,
    })
    rows.value = result.items
    total.value = result.total
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div><h1 class="page-title">Trace 与失败查询</h1><p class="page-subtitle">跨运行定位失败 Case、Trace ID 和可回放上下文</p></div>
    </div>
    <div class="filters-band">
      <ElInput v-model="traceId" clearable placeholder="Trace ID" style="width: 280px" @keyup.enter="load"><template #prefix><Search :size="15" /></template></ElInput>
      <ElInputNumber v-model="runId" :min="1" placeholder="Run ID" controls-position="right" />
      <ElCheckbox v-model="failureOnly">仅失败结果</ElCheckbox>
      <ElButton type="primary" @click="load">查询</ElButton>
    </div>
    <section class="panel">
      <ElTable v-if="rows.length" v-loading="loading" :data="rows" row-key="id">
        <ElTableColumn label="Result" width="100"><template #default="{ row }">#{{ row.id }}</template></ElTableColumn>
        <ElTableColumn label="Run" width="100"><template #default="{ row }"><a class="table-link" @click="router.push(`/runs/${row.run_id}`)">#{{ row.run_id }}</a></template></ElTableColumn>
        <ElTableColumn label="版本" width="110"><template #default="{ row }"><StatusTag :value="row.version_role" /></template></ElTableColumn>
        <ElTableColumn label="失败分类" min-width="180"><template #default="{ row }"><span :class="row.failure_type ? 'danger-text' : 'success-text'">{{ row.failure_type ?? '通过' }}</span></template></ElTableColumn>
        <ElTableColumn prop="latency_ms" label="延迟 ms" width="110" />
        <ElTableColumn label="Trace ID" min-width="260"><template #default="{ row }"><a v-if="row.trace_url" class="table-link mono" :href="row.trace_url" target="_blank">{{ row.trace_id }}</a><span v-else class="muted">UNKNOWN</span></template></ElTableColumn>
      </ElTable>
      <EmptyState v-else title="没有匹配结果" description="调整 Run、Trace ID 或失败筛选条件。" />
      <div v-if="total > 20" class="pagination-row"><ElPagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next, total" @current-change="load" /></div>
    </section>
  </div>
</template>
