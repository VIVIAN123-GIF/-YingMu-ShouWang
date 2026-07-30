<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init, use } from 'echarts/core'
import { BarChart, HeatmapChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'

use([BarChart, HeatmapChart, LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, VisualMapComponent, SVGRenderer])

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '300px' },
  ariaLabel: { type: String, default: '数据趋势图' },
})

const chartRef = ref(null)
let chart
let observer

function render() {
  if (!chartRef.value) return
  if (!chart) chart = init(chartRef.value, null, { renderer: 'svg' })
  chart.setOption(props.option, true)
}

onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(chartRef.value)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <div ref="chartRef" class="chart-panel" :style="{ height }" role="img" :aria-label="ariaLabel"></div>
</template>
