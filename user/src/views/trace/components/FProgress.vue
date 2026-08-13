<script setup lang="ts">
/**
 * FProgress — 横轴 F 累积进度条（f_value / R_S）。
 *
 * 纯手写（div + tailwind），无图表库依赖。r_s 优先取后端 /h/state 返回值
 * （由父组件传入）；未提供时回退到后端默认 200.0（与 analysis.r_s 对齐）。
 * 后端公式为三次方和 F_d = Σ s_j³（非平方和）。
 */
import { computed } from 'vue'

const props = defineProps<{ fValue: number; rS?: number }>()

const R_S_DEFAULT = 200.0
const rS = computed(() => props.rS ?? R_S_DEFAULT)
const ratio = computed(() => rS.value > 0 ? Math.min(1, props.fValue / rS.value) : 0)
const overThreshold = computed(() => props.fValue > rS.value)
const barCls = computed(() =>
  overThreshold.value ? 'bg-red-500' : ratio.value > 0.7 ? 'bg-amber-500' : 'bg-indigo-500',
)
</script>

<template>
  <div class="w-full">
    <div class="flex items-center justify-between text-[10px] mb-1">
      <span class="text-gray-400">F 累积 (Σ s³)</span>
      <span class="font-mono tabular-nums" :class="overThreshold ? 'text-red-600 font-semibold' : 'text-gray-500'">
        {{ Number(fValue).toFixed(1) }} / {{ rS.toFixed(1) }}
      </span>
    </div>
    <div class="relative h-2.5 bg-gray-100 rounded-full overflow-hidden">
      <div class="absolute inset-y-0 left-0 rounded-full transition-all" :class="barCls" :style="{ width: `${ratio * 100}%` }"></div>
      <!-- R_S 阈值刻度（右沿） -->
      <div class="absolute inset-y-0 right-0 w-px bg-gray-300"></div>
    </div>
    <div v-if="overThreshold" class="text-[10px] text-red-600 mt-1">已超 R_S，触发横轴确认</div>
  </div>
</template>
