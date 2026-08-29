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
  replace: { type: Boolean, default: true },
  drawAnimation: { type: Boolean, default: false },
  drawColor: { type: String, default: '' },
  drawDuration: { type: Number, default: 4200 },
  drawDelay: { type: Number, default: 500 },
  pointAnimation: { type: Boolean, default: false },
  pointColor: { type: String, default: '' },
  ariaLabel: { type: String, default: '数据趋势图' },
})

const chartRef = ref(null)
let chart
let observer
let hasAnimated = false

function animateLinePath() {
  if (!props.drawAnimation || !props.drawColor || !chartRef.value || typeof window === 'undefined') return
  let attempts = 0
  const findAndAnimate = () => {
    const colors = props.drawColor.split(',').map((value) => value.replace(/\s/g, '').toLowerCase()).filter(Boolean)
    const targets = [...chartRef.value.querySelectorAll('path')].filter((path) => {
      const stroke = (path.getAttribute('stroke') || path.style.stroke || '').replace(/\s/g, '').toLowerCase()
      return colors.some((color) => stroke === color)
        || ['rgb(22,119,194)', 'rgb(134,144,156)', 'rgb(255,125,0)'].includes(stroke)
    })
    if (!targets.length || targets.some((target) => !target.getTotalLength)) {
      if (attempts < 10) { attempts += 1; window.setTimeout(findAndAnimate, 40) }
      return
    }
    targets.forEach((target) => {
      const length = target.getTotalLength()
      target.style.strokeDasharray = `${length}`
      target.style.strokeDashoffset = `${length}`
      if (target.animate) target.animate([{ strokeDashoffset: length }, { strokeDashoffset: 0 }], { duration: props.drawDuration, delay: props.drawDelay, easing: 'cubic-bezier(.4,0,.2,1)', fill: 'forwards' })
      else {
        target.style.transition = `stroke-dashoffset ${props.drawDuration}ms cubic-bezier(.4,0,.2,1) ${props.drawDelay}ms`
        target.getBoundingClientRect()
        target.style.strokeDashoffset = '0'
      }
    })
  }
  requestAnimationFrame(findAndAnimate)
}

function animateAreaPath() {
  if (!props.drawAnimation || !chartRef.value || typeof window === 'undefined') return
  let attempts = 0
  const findAndAnimate = () => {
    const target = [...chartRef.value.querySelectorAll('path')].find((path) => {
      const fill = (path.getAttribute('fill') || path.style.fill || '').trim().toLowerCase()
      return fill.startsWith('url(')
    })
    if (!target) {
      if (attempts < 10) { attempts += 1; window.setTimeout(findAndAnimate, 40) }
      return
    }
    target.style.clipPath = 'inset(0 100% 0 0)'
    if (target.animate) {
      target.animate(
        [{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0% 0 0)' }],
        { duration: props.drawDuration, delay: props.drawDelay, easing: 'cubic-bezier(.4,0,.2,1)', fill: 'forwards' },
      )
    } else {
      target.style.transition = `clip-path ${props.drawDuration}ms cubic-bezier(.4,0,.2,1) ${props.drawDelay}ms`
      target.getBoundingClientRect()
      target.style.clipPath = 'inset(0 0% 0 0)'
    }
  }
  requestAnimationFrame(findAndAnimate)
}

function animatePointPaths() {
  if (!props.pointAnimation || !props.pointColor || !chartRef.value || typeof window === 'undefined') return
  let attempts = 0
  const findAndAnimate = () => {
    const color = props.pointColor.replace(/\s/g, '').toLowerCase()
    const points = [...chartRef.value.querySelectorAll('path')].filter((path) => {
      const fill = (path.getAttribute('fill') || path.style.fill || '').replace(/\s/g, '').toLowerCase()
      const stroke = (path.getAttribute('stroke') || path.style.stroke || '').replace(/\s/g, '').toLowerCase()
      return [fill, stroke].some((value) => value === color || value === 'rgb(22,119,194)')
    })
    if (!points.length) {
      if (attempts < 10) { attempts += 1; window.setTimeout(findAndAnimate, 40) }
      return
    }
    points.forEach((point, index) => {
      point.style.opacity = '0'
      if (point.animate) {
        point.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: index * 260, easing: 'cubic-bezier(.4,0,.2,1)', fill: 'forwards' })
      } else {
        point.style.transition = `opacity 800ms cubic-bezier(.4,0,.2,1) ${index * 260}ms`
        point.getBoundingClientRect()
        point.style.opacity = '1'
      }
    })
  }
  requestAnimationFrame(findAndAnimate)
}

function render() {
  if (!chartRef.value) return
  if (!chart) chart = init(chartRef.value, null, { renderer: 'svg' })
  chart.setOption(props.option, props.replace)
  if (!hasAnimated) {
    animatePointPaths()
    animateAreaPath()
    animateLinePath()
    hasAnimated = true
  }
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
