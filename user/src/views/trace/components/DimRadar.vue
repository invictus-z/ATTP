<script setup lang="ts">
/**
 * DimRadar — 4 维雷达图（纯 SVG，无图表库）。
 *
 * 四轴：d1 意图对齐（上）/ d2 能力（右）/ d3 注入（下）/ d4 外泄（左），各 [0,10]。
 */
import { computed } from 'vue'
import { DIMENSION_LABELS } from '../types'

const props = defineProps<{ dimensions: number[] | [number, number, number, number]; size?: number }>()

const size = computed(() => props.size ?? 120)
const center = computed(() => size.value / 2)
const radius = computed(() => size.value / 2 - 20)

// d1=上, d2=右, d3=下, d4=左
const angles = [-90, 0, 90, 180]
const gridRings = [2.5, 5, 7.5, 10]

function pt(axisIdx: number, value: number): [number, number] {
  const ang = (angles[axisIdx] * Math.PI) / 180
  const r = (Math.max(0, Math.min(10, value)) / 10) * radius.value
  return [center.value + r * Math.cos(ang), center.value + r * Math.sin(ang)]
}

const dataStr = computed(() => {
  const dims = (props.dimensions && props.dimensions.length === 4) ? props.dimensions : [0, 0, 0, 0]
  return dims.map((d, i) => pt(i, d).join(',')).join(' ')
})

const labelPts = computed(() =>
  angles.map((a) => {
    const ang = (a * Math.PI) / 180
    return [center.value + (radius.value + 11) * Math.cos(ang), center.value + (radius.value + 11) * Math.sin(ang)]
  }),
)
</script>

<template>
  <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" class="overflow-visible">
    <!-- 同心网格 -->
    <polygon v-for="r in gridRings" :key="r"
      :points="angles.map((_, i) => pt(i, r).join(',')).join(' ')"
      fill="none" stroke="#e5e7eb" stroke-width="1"
    />
    <!-- 四轴 -->
    <line v-for="(a, i) in angles" :key="i"
      :x1="center" :y1="center" :x2="pt(i, 10)[0]" :y2="pt(i, 10)[1]"
      stroke="#e5e7eb" stroke-width="1"
    />
    <!-- 数据多边形 -->
    <polygon :points="dataStr" fill="rgba(99,102,241,0.25)" stroke="#6366f1" stroke-width="1.5" />
    <!-- 维度标签 -->
    <text v-for="(lp, i) in labelPts" :key="i"
      :x="lp[0]" :y="lp[1]" text-anchor="middle" dominant-baseline="middle"
      style="font-size:9px" class="fill-gray-400"
    >{{ DIMENSION_LABELS[i] }}</text>
  </svg>
</template>
