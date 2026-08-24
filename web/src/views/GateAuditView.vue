<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import EmptyState from '@/components/EmptyState.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api, apiError } from '@/services/api'
import type { GateResult } from '@/types/api'

const router = useRouter()
const rows = ref<GateResult[]>([])
const total = ref(0)
const decision = ref('')
const page = ref(1)
const loading = ref(false)
const reasonLabels = (row: GateResult) => row.reasons.map((item) => item.rule_id).join('、')

async function load() {
  loading.value = true
  try {
    const result = await api.gateAudits({ decision: decision.value || undefined, page: page.value, page_size: 20 })
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
    <div class="page-header"><div><h1 class="page-title">发布门禁审计</h1><p class="page-subtitle">跨运行查看 SHIP、WARN、BLOCK 与触发规则</p></div></div>
    <div class="filters-band">
      <ElSelect v-model="decision" clearable placeholder="全部决策" style="width: 180px" @change="load"><ElOption label="SHIP" value="ship" /><ElOption label="WARN" value="warn" /><ElOption label="BLOCK" value="block" /></ElSelect>
    </div>
    <section class="panel">
      <ElTable v-if="rows.length" v-loading="loading" :data="rows">
        <ElTableColumn label="Run" width="100"><template #default="{ row }"><a class="table-link" @click="router.push(`/runs/${row.run_id}/gate`)">#{{ row.run_id }}</a></template></ElTableColumn>
        <ElTableColumn label="决策" width="120"><template #default="{ row }"><StatusTag :value="row.decision" /></template></ElTableColumn>
        <ElTableColumn prop="policy_id" label="策略版本 ID" width="130" />
        <ElTableColumn label="触发规则" min-width="360"><template #default="{ row }"><span v-if="row.reasons.length">{{ reasonLabels(row) }}</span><span v-else class="muted">无阻断或告警规则</span></template></ElTableColumn>
        <ElTableColumn label="评估时间" min-width="190"><template #default="{ row }">{{ new Date(row.evaluated_at).toLocaleString('zh-CN') }}</template></ElTableColumn>
      </ElTable>
      <EmptyState v-else title="暂无门禁记录" description="完成带 GatePolicy 的 Baseline/Candidate 运行后生成。" />
      <div v-if="total > 20" class="pagination-row"><ElPagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next, total" @current-change="load" /></div>
    </section>
  </div>
</template>
