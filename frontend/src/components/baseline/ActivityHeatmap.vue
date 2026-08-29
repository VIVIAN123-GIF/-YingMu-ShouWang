<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { VideoPlay } from '@element-plus/icons-vue'
import { init, use } from 'echarts/core'
import { HeatmapChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { DEFAULT_ACTIVITY_HEATMAP, normalizeActivityHeatmap } from '../../data/activityHeatmapData'

use([HeatmapChart, ScatterChart, GridComponent, TooltipComponent, VisualMapComponent, SVGRenderer])

const props = defineProps({
  data: { type: Object, default: () => DEFAULT_ACTIVITY_HEATMAP },
  enablePlayAnimation: { type: Boolean, default: false }, // 答辩演示开关
  enableAbnormalMark: { type: Boolean, default: false }, // 风险分析开关
  abnormalPoints: { type: Array, default: () => [] },
})

const chartElement = ref(null)
const activeFilter = ref('all')
const hoverCell = ref(null)
const visibleDayCount = ref(Number.POSITIVE_INFINITY)
const playing = ref(false)
let chart
let resizeObserver
let playTimer

const normalized = computed(() => normalizeActivityHeatmap(props.data))
const legendItems = Object.freeze([
  { key: 'low', label: '活动较少' },
  { key: 'high', label: '活动较多' },
])

function isAbnormal(x, y) {
  return props.abnormalPoints.some((point) => (
    (point.x === x && point.y === y)
    || (point.date === normalized.value.days[x] && point.period === normalized.value.periods[y])
  ))
}

function interpretation(value) {
  if (value >= 60) return '该时间段老人居家活动频次较高'
  if (value >= 35) return '该时间段老人居家活动频次较为平稳'
  return '该时间段老人居家活动频次较少'
}

function matchesFilter(value) {
  if (activeFilter.value === 'low') return value < 50
  if (activeFilter.value === 'high') return value >= 50
  return true
}

function cellOpacity(x, y, value) {
  if (x >= visibleDayCount.value || !matchesFilter(value)) return 0.12
  if (!hoverCell.value) return 1
  if (hoverCell.value.x === x && hoverCell.value.y === y) return 1
  if (hoverCell.value.x === x || hoverCell.value.y === y) return 0.72
  return 0.25
}

function heatmapData() {
  return normalized.value.values.map(([x, y, value], index) => ({
    value: [x, y, value],
    itemStyle: {
      opacity: cellOpacity(x, y, value),
      borderColor: hoverCell.value?.x === x && hoverCell.value?.y === y ? '#1677c2' : '#fff',
      borderWidth: hoverCell.value?.x === x && hoverCell.value?.y === y ? 3 : 1,
    },
    label: { color: value >= 55 ? '#fff' : '#1f2937' },
    animationDelay: index * 35,
  }))
}

function abnormalData() {
  if (!props.enableAbnormalMark) return []
  return normalized.value.values
    .filter(([x, y]) => isAbnormal(x, y))
    .map(([x, y, value]) => [x, y, value])
}

function tooltipFormatter(params) {
  const [x, y, value] = params.value
  const warning = props.enableAbnormalMark && isAbnormal(x, y)
    ? '<br/><span style="color:#8a5a0a">⚠️ 该时段活动强度相比往日出现明显变化，请多留意老人状态。</span>'
    : ''
  return [
    `日期：${normalized.value.days[x]}`,
    `时段：${normalized.value.periods[y]}`,
    `活动强度：<b>${value}</b>`,
    `解读：${interpretation(value)}${warning}`,
  ].join('<br/>')
}

const option = computed(() => ({
  animation: true,
  animationDuration: 650,
  animationDurationUpdate: 260,
  animationEasing: 'cubicOut',
  grid: { left: 76, right: 24, top: 20, bottom: 44 },
  tooltip: {
    trigger: 'item',
    confine: true,
    backgroundColor: 'rgba(255,255,255,.98)',
    borderColor: '#d1d5db',
    textStyle: { color: '#1f2937', fontSize: 15, lineHeight: 24 },
    extraCssText: 'max-width:320px;white-space:normal;box-shadow:0 10px 28px rgba(17,17,17,.12);border-radius:8px;padding:12px 14px;',
    formatter: tooltipFormatter,
  },
  xAxis: {
    type: 'category', data: normalized.value.days,
    axisTick: { show: false }, axisLine: { lineStyle: { color: '#9ca3af' } },
    axisLabel: { color: '#374151', fontSize: 15, margin: 12 },
  },
  yAxis: {
    type: 'category', data: normalized.value.periods,
    axisTick: { show: false }, axisLine: { show: false },
    axisLabel: { color: '#374151', fontSize: 16, margin: 14 },
  },
  visualMap: {
    show: false, min: 0, max: 75,
    inRange: { color: ['#ecf9f0', '#73a8d8', '#1677c2'] },
  },
  series: [
    {
      id: 'activity', name: '活动强度', type: 'heatmap', data: heatmapData(),
      label: { show: true, fontSize: 15, formatter: ({ value }) => value[2] },
      animationDelay: (index) => index * 35,
      emphasis: { disabled: true },
    },
    {
      id: 'abnormal', name: '基线异常', type: 'scatter', data: abnormalData(),
      symbol: 'circle', symbolSize: 9, symbolOffset: [28, -22],
      itemStyle: { color: '#ff7d00', borderColor: '#fff', borderWidth: 2 },
      tooltip: { show: false }, z: 5,
    },
  ],
}))

function render() {
  if (!chartElement.value) return
  if (!chart) chart = init(chartElement.value, null, { renderer: 'svg' })
  chart.setOption(option.value, { notMerge: false })
}

function setFilter(key) {
  activeFilter.value = activeFilter.value === key ? 'all' : key
}

function playWeek() {
  if (playing.value) return
  clearInterval(playTimer)
  visibleDayCount.value = 0
  playing.value = true
  playTimer = window.setInterval(() => {
    visibleDayCount.value += 1
    if (visibleDayCount.value >= normalized.value.days.length) {
      clearInterval(playTimer)
      playing.value = false
    }
  }, 520)
}

onMounted(async () => {
  await nextTick()
  render()
  chart.on('mouseover', 'series.heatmap', ({ value }) => { hoverCell.value = { x: value[0], y: value[1] } })
  chart.on('mouseout', 'series.heatmap', () => { hoverCell.value = null })
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(chartElement.value)
})

watch(option, render, { deep: true })
onBeforeUnmount(() => {
  clearInterval(playTimer)
  resizeObserver?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <section class="activity-heatmap" aria-labelledby="activity-heatmap-title">
    <header>
      <div>
        <h2 id="activity-heatmap-title">近七日活动热力图</h2>
        <p>色块颜色越深，代表老人该时间段居家活动越频繁</p>
      </div>
      <el-button v-if="enablePlayAnimation" :loading="playing" @click="playWeek">
        <el-icon><VideoPlay /></el-icon>{{ playing ? '回放中' : '播放一周' }}
      </el-button>
    </header>

    <div ref="chartElement" class="heatmap-canvas" role="img" aria-label="近七日分时活动强度热力图"></div>

    <div class="heatmap-legend" aria-label="活动强度筛选">
      <button
        v-for="item in legendItems"
        :key="item.key"
        type="button"
        :class="{ active: activeFilter === item.key }"
        :aria-pressed="activeFilter === item.key"
        @click="setFilter(item.key)"
      >{{ item.label }}</button>
      <span class="legend-gradient" aria-hidden="true"></span>
    </div>

    <p class="heatmap-note"><span aria-hidden="true">ⓘ</span> 热力图只表达分时活动强度，不代表真实房间轨迹；房间区域数据待区域标定完成后接入。</p>
  </section>
</template>

<style scoped>
.activity-heatmap { width: 100%; }
.activity-heatmap > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.activity-heatmap h2 { margin: 0; color: #1d2129; font-size: 18px; font-weight: 600; }
.activity-heatmap header p { margin: 6px 0 0; color: #4e5969; font-size: 14px; line-height: 1.5; }
.heatmap-canvas { width: 100%; height: 390px; }
.heatmap-legend { display: flex; align-items: center; justify-content: center; gap: 10px; }
.heatmap-legend button { min-height: 38px; padding: 6px 12px; color: #4e5969; background: #fff; border: 1px solid #e5e6eb; border-radius: 7px; cursor: pointer; }
.heatmap-legend button:hover, .heatmap-legend button.active { color: #1677c2; border-color: #1677c2; background: #eef6fc; }
.heatmap-legend button:first-of-type { order: 1; }
.heatmap-legend button:last-of-type { order: 3; }
.legend-gradient { order: 2; width: 190px; height: 16px; border-radius: 4px; background: linear-gradient(90deg, #ecf9f0, #73a8d8, #1677c2); }
.heatmap-note { margin: 18px 0 0; color: #86909c; font-size: 12px; line-height: 1.6; text-align: center; }

@media (max-width: 767px) {
  .activity-heatmap > header { flex-direction: column; }
  .activity-heatmap h2 { font-size: 18px; }
  .heatmap-canvas { height: 340px; }
  .heatmap-legend { flex-wrap: wrap; }
  .legend-gradient { order: -1; width: 100%; }
  .heatmap-note { text-align: left; }
}
</style>
