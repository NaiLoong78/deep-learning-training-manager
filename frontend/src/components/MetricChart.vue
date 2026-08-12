<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { MetricRow } from '../types'

const props = defineProps<{ rows: MetricRow[] }>()
const chartEl = ref<HTMLDivElement>()
let chart: echarts.ECharts | undefined

const series = computed(() => {
  const groups = new Map<string, [number, number][]>()
  props.rows.forEach((row, index) => {
    const list = groups.get(row.name) || []
    list.push([row.step ?? row.epoch ?? index, row.value])
    groups.set(row.name, list)
  })
  return Array.from(groups.entries()).map(([name, data]) => ({ name, type: 'line', showSymbol: false, smooth: true, data }))
})

function render() {
  if (!chartEl.value) return
  chart ||= echarts.init(chartEl.value)
  chart.setOption({
    backgroundColor: 'transparent',
    color: ['#315f8c', '#4f7f62', '#a66a3f', '#8a5f8f', '#b24f55'],
    tooltip: { trigger: 'axis', backgroundColor: '#ffffff', borderColor: '#d6dbe1', textStyle: { color: '#27313d' } },
    legend: { type: 'scroll', top: 0, textStyle: { color: '#667281' } },
    grid: { left: 48, right: 20, top: 42, bottom: 36 },
    xAxis: { type: 'value', name: 'Epoch / Step', nameLocation: 'middle', nameGap: 27, axisLine: { lineStyle: { color: '#aeb6c0' } }, axisLabel: { color: '#76818e' }, splitLine: { lineStyle: { color: '#edf0f3' } } },
    yAxis: { type: 'value', scale: true, axisLine: { lineStyle: { color: '#aeb6c0' } }, axisLabel: { color: '#76818e' }, splitLine: { lineStyle: { color: '#edf0f3' } } },
    series: series.value,
  }, true)
}

function resize() { chart?.resize() }
onMounted(() => { nextTick(render); window.addEventListener('resize', resize) })
onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart?.dispose() })
watch(series, () => nextTick(render), { deep: true })
</script>

<template><div ref="chartEl" class="metric-chart" /></template>
