<script setup lang="ts">
import { ArrowRight, FlaskConical, Plus } from '@lucide/vue'
import { ElMessage } from 'element-plus'
import type { EChartsOption } from 'echarts'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import EmptyState from '@/components/EmptyState.vue'
import OperationalChart from '@/components/OperationalChart.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api, apiError } from '@/services/api'
import type { DashboardSummary, EvalRun } from '@/types/api'

const router = useRouter()
const summary = ref<DashboardSummary | null>(null)
const runs = ref<EvalRun[]>([])
const loading = ref(true)
const bootstrapping = ref(false)

const trendOption = computed<EChartsOption>(() => ({
  animation: false,
  color: ['#2f7df6', '#c13232'],
  tooltip: { trigger: 'axis' },
  grid: { left: 38, right: 18, top: 22, bottom: 32 },
  xAxis: {
    type: 'category',
    data: summary.value?.run_trend.map((item) => String(item.date)) ?? [],
    axisLine: { lineStyle: { color: '#dfe3e8' } },
    axisLabel: { color: '#667085', fontSize: 11 },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    splitLine: { lineStyle: { color: '#eef1f5' } },
    axisLabel: { color: '#667085' },
  },
  series: [
    {
      name: '运行数',
      type: 'line',
      smooth: false,
      symbolSize: 6,
      areaStyle: { color: 'rgba(47,125,246,.08)' },
      data: summary.value?.run_trend.map((item) => Number(item.total ?? 0)) ?? [],
    },
  ],
}))

async function load() {
  loading.value = true
  try {
    const [summaryData, runPage] = await Promise.all([api.dashboard(), api.runs({ page_size: 8 })])
    summary.value = summaryData
    runs.value = runPage.items
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
}

async function bootstrap() {
  bootstrapping.value = true
  try {
    const result = await api.bootstrapDemo()
    ElMessage.success(
      result.created_resources.length
        ? `Demo Fixture 已初始化：${result.created_resources.length} 项资源`
        : 'Demo Fixture 已存在',
    )
    await load()
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    bootstrapping.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">质量总览</h1>
        <p class="page-subtitle">当前组织的冻结评测、失败分布与发布门禁状态</p>
      </div>
      <div class="page-actions">
        <ElButton :loading="bootstrapping" @click="bootstrap">
          <FlaskConical :size="15" /> Demo Fixture
        </ElButton>
        <ElButton type="primary" @click="router.push('/runs')">
          <Plus :size="15" /> 创建评测运行
        </ElButton>
      </div>
    </div>

    <div class="metric-strip" v-loading="loading">
      <div class="metric">
        <div class="metric-label">活跃目标</div>
        <div class="metric-value">{{ summary?.active_target_count ?? '—' }}</div>
        <div class="metric-detail">登记目标 {{ summary?.target_count ?? '—' }}</div>
      </div>
      <div class="metric">
        <div class="metric-label">评测运行</div>
        <div class="metric-value">{{ summary?.run_count ?? '—' }}</div>
        <div class="metric-detail">已完成 {{ summary?.completed_run_count ?? '—' }}</div>
      </div>
      <div class="metric">
        <div class="metric-label">失败运行</div>
        <div class="metric-value danger-text">{{ summary?.failed_run_count ?? '—' }}</div>
        <div class="metric-detail">仅统计真实 FAILED 状态</div>
      </div>
      <div class="metric">
        <div class="metric-label">最近门禁</div>
        <div class="metric-value">
          <StatusTag
            v-if="summary?.latest_gate_decisions[0]"
            :value="summary.latest_gate_decisions[0].decision"
          />
          <span v-else>—</span>
        </div>
        <div class="metric-detail">
          {{ summary?.latest_gate_decisions[0] ? `Run #${summary.latest_gate_decisions[0].run_id}` : '暂无决策' }}
        </div>
      </div>
    </div>

    <div class="dashboard-grid">
      <section class="panel">
        <div class="panel-header"><h2 class="panel-title">运行趋势</h2><span class="muted">近 14 个活跃日期</span></div>
        <div class="panel-body"><OperationalChart :option="trendOption" /></div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2 class="panel-title">失败分类</h2><span class="muted">跨运行聚合</span></div>
        <div class="failure-list">
          <div v-for="item in summary?.failure_categories" :key="item.failure_type" class="failure-row">
            <span>{{ item.failure_type }}</span><strong>{{ item.count }}</strong>
          </div>
          <EmptyState
            v-if="!summary?.failure_categories.length"
            title="暂无失败分类"
            description="当前组织尚未记录失败 Case。"
          />
        </div>
      </section>
    </div>

    <section class="panel recent-panel">
      <div class="panel-header">
        <h2 class="panel-title">最近评测运行</h2>
        <ElButton text @click="router.push('/runs')">查看全部 <ArrowRight :size="14" /></ElButton>
      </div>
      <ElTable v-if="runs.length" v-loading="loading" :data="runs" row-key="id">
        <ElTableColumn label="Run" width="100">
          <template #default="{ row }"><a class="table-link" @click="router.push(`/runs/${row.id}`)">#{{ row.id }}</a></template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="120"><template #default="{ row }"><StatusTag :value="row.status" /></template></ElTableColumn>
        <ElTableColumn prop="expected_case_count" label="Cases" width="100" />
        <ElTableColumn label="进度" min-width="160"><template #default="{ row }">{{ row.completed_case_count }} / {{ row.expected_case_count }}</template></ElTableColumn>
        <ElTableColumn label="创建时间" min-width="190"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template></ElTableColumn>
      </ElTable>
      <EmptyState v-else title="暂无评测运行" description="初始化 Demo Fixture 或登记真实目标后创建运行。" />
    </section>
  </div>
</template>

<style scoped>
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(300px, .75fr); gap: 16px; margin-bottom: 16px; }
.failure-list { min-height: 312px; padding: 12px 18px; }
.failure-row { min-height: 48px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border); font-size: 13px; }
.failure-row strong { font-variant-numeric: tabular-nums; }
.recent-panel { margin-top: 16px; }
@media (max-width: 980px) { .dashboard-grid { grid-template-columns: 1fr; } }
</style>
