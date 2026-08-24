<script setup lang="ts">
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  labels: string[]
  baseline: number[]
  candidate: number[]
}>()

const root = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null

function render() {
  if (!root.value) return
  chart ??= init(root.value)
  chart.setOption({
    animationDuration: 260,
    color: ['#98a2b3', '#2563eb'],
    grid: { left: 44, right: 16, top: 38, bottom: 36 },
    tooltip: { trigger: 'axis' },
    legend: { top: 5, right: 8, itemWidth: 10, itemHeight: 8, textStyle: { fontSize: 11 } },
    xAxis: { type: 'category', data: props.labels, axisLabel: { fontSize: 10 }, axisTick: { show: false } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', fontSize: 10 }, splitLine: { lineStyle: { color: '#edf0f4' } } },
    series: [
      { name: 'Baseline', type: 'bar', data: props.baseline, barMaxWidth: 30, itemStyle: { borderRadius: [3, 3, 0, 0] } },
      { name: 'Candidate', type: 'bar', data: props.candidate, barMaxWidth: 30, itemStyle: { borderRadius: [3, 3, 0, 0] } },
    ],
  })
}

function resize() { chart?.resize() }
onMounted(async () => { await nextTick(); render(); window.addEventListener('resize', resize) })
watch(() => [props.labels, props.baseline, props.candidate], render, { deep: true })
onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart?.dispose() })
</script>

<template><div ref="root" class="metric-chart" /></template>

<style scoped>.metric-chart { width: 100%; height: 300px; }</style>
