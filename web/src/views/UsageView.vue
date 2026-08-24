<script setup lang="ts">
import { RotateCcw } from '@lucide/vue'
import { ElMessage } from 'element-plus'
import type { EChartsOption } from 'echarts'
import { computed, onMounted, ref } from 'vue'

import OperationalChart from '@/components/OperationalChart.vue'
import { api, apiError } from '@/services/api'
import { useCatalogStore } from '@/stores/catalog'
import type { UsageSummary } from '@/types/api'
import { formatCost, formatNumber } from '@/utils/format'

const catalog = useCatalogStore()
const summary = ref<UsageSummary | null>(null)
const loading = ref(false)
const groupBy = ref('target')
const targetId = ref<number | undefined>()

const chartOption = computed<EChartsOption>(() => ({
  animation: false,
  color: ['#111827', '#2f7df6'],
  tooltip: { trigger: 'axis' },
  legend: { right: 8, top: 0, textStyle: { color: '#667085', fontSize: 11 } },
  grid: { left: 44, right: 20, top: 42, bottom: 52 },
  xAxis: {
    type: 'category',
    data: summary.value?.groups.map((item) => item.key) ?? [],
    axisLabel: { color: '#667085', rotate: 15 },
    axisLine: { lineStyle: { color: '#dfe3e8' } },
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: '#eef1f5' } },
    axisLabel: { color: '#667085' },
  },
  series: [
    {
      name: 'Input Token',
      type: 'bar',
      barMaxWidth: 28,
      data: summary.value?.groups.map((item) => item.input_tokens) ?? [],
    },
    {
      name: 'Output Token',
      type: 'bar',
      barMaxWidth: 28,
      data: summary.value?.groups.map((item) => item.output_tokens) ?? [],
    },
  ],
}))

async function load() {
  loading.value = true
  try {
    await catalog.refresh()
    summary.value = await api.usage({
      group_by: groupBy.value,
      target_id: targetId.value,
    })
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
      <div>
        <h1 class="page-title">用量与成本</h1>
        <p class="page-subtitle">模型 Token、外部工具费用和 UNKNOWN 遥测比例</p>
      </div>
      <ElButton :loading="loading" @click="load"><RotateCcw :size="15" /> 刷新</ElButton>
    </div>
    <div class="filters-band">
      <ElSelect v-model="targetId" clearable placeholder="全部目标" style="width: 220px" @change="load">
        <ElOption v-for="target in catalog.targets" :key="target.id" :label="target.name" :value="target.id" />
      </ElSelect>
      <ElSegmented v-model="groupBy" :options="[{ label: '目标', value: 'target' }, { label: '版本', value: 'version' }, { label: '模型', value: 'model' }, { label: '日期', value: 'day' }]" @change="load" />
    </div>
    <div class="metric-strip" v-loading="loading">
      <div class="metric"><div class="metric-label">Input Token</div><div class="metric-value">{{ formatNumber(summary?.input_tokens) }}</div><div class="metric-detail">缺失保持 UNKNOWN</div></div>
      <div class="metric"><div class="metric-label">Output Token</div><div class="metric-value">{{ formatNumber(summary?.output_tokens) }}</div><div class="metric-detail">含已观测输出</div></div>
      <div class="metric"><div class="metric-label">模型费用</div><div class="metric-value">{{ formatCost(summary?.model_cost) }}</div><div class="metric-detail">PricingSnapshot 版本化</div></div>
      <div class="metric"><div class="metric-label">外部工具费用</div><div class="metric-value">{{ formatCost(summary?.external_tool_cost) }}</div><div class="metric-detail">与模型费用分列</div></div>
    </div>
    <section class="panel usage-chart">
      <div class="panel-header">
        <h2 class="panel-title">Token 分布</h2>
        <span class="muted">用量 UNKNOWN {{ ((summary?.unknown_measurement_ratio ?? 0) * 100).toFixed(1) }}% · 费用 UNKNOWN {{ ((summary?.unknown_cost_ratio ?? 0) * 100).toFixed(1) }}%</span>
      </div>
      <div class="panel-body"><OperationalChart :option="chartOption" /></div>
    </section>
    <section class="panel usage-table">
      <div class="panel-header"><h2 class="panel-title">分组明细</h2></div>
      <ElTable :data="summary?.groups ?? []">
        <ElTableColumn prop="key" label="分组" min-width="180" />
        <ElTableColumn label="Input" min-width="130"><template #default="{ row }">{{ formatNumber(row.input_tokens) }}</template></ElTableColumn>
        <ElTableColumn label="Output" min-width="130"><template #default="{ row }">{{ formatNumber(row.output_tokens) }}</template></ElTableColumn>
        <ElTableColumn label="模型费用" min-width="140"><template #default="{ row }">{{ formatCost(row.model_cost) }}</template></ElTableColumn>
        <ElTableColumn label="工具费用" min-width="140"><template #default="{ row }">{{ formatCost(row.external_tool_cost) }}</template></ElTableColumn>
        <ElTableColumn label="UNKNOWN" width="120"><template #default="{ row }">{{ (row.unknown_ratio * 100).toFixed(1) }}%</template></ElTableColumn>
      </ElTable>
    </section>
  </div>
</template>

<style scoped>
.usage-chart { margin-bottom: 16px; }
</style>
