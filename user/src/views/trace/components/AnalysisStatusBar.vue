<script setup lang="ts">
/**
 * AnalysisStatusBar — 分析状态条（刷新状态 + 状态文案 / 触发分析）。
 *
 * 纵向（session 级）与横向（did 级）共用，由父组件传入对应状态与禁用条件。
 *
 * 设计要点：
 * - 纵向逐跳改版后打分自动进行，无需手动触发：纵向实例传 `showTrigger=false`
 *   隐藏「触发分析」按钮，仅由 statusKind 反映「分析中 / 空闲」。
 * - 横向仍保留「触发分析」按钮（手动触发横轴确认），由 triggerDisabled 控制可点击。
 *
 * statusKind 状态词汇：running | completed | failed | pending | uptodate | idle
 */
import {
  Loader2, Zap, RefreshCw, CheckCircle2, XCircle, Clock,
} from 'lucide-vue-next'
import type { AnalysisStatus } from '../types'

defineProps<{
  status: AnalysisStatus | null
  statusKind: 'idle' | 'running' | 'completed' | 'failed' | 'pending' | 'uptodate'
  polling: boolean
  /** 仅横向（showTrigger=true）需要；纵向隐藏触发键时可不传。 */
  triggerLoading?: boolean
  refreshDisabled: boolean
  triggerDisabled?: boolean
  /** 是否显示「触发分析」按钮。纵向逐跳改版后置 false（打分自动进行）。默认 true。 */
  showTrigger?: boolean
}>()

defineEmits<{
  (e: 'refresh'): void
  (e: 'trigger'): void
}>()

/** phase 本地化（纵 scoring/idle；横 selecting/confirming/saving_results）。 */
function phaseLabel(phase?: string): string {
  switch (phase) {
    case 'scoring': return '逐跳打分中'
    case 'selecting': return '选会话中'
    case 'confirming': return '确认中'
    case 'saving_results': return '保存结论中'
    case 'idle': return '空闲'
    case 'starting': return '启动中'
    default: return phase || ''
  }
}
</script>

<template>
  <div class="border-t border-gray-100 pt-4 flex items-center justify-between gap-3">
    <button @click="$emit('refresh')" :disabled="refreshDisabled"
      class="px-3 py-2 text-[13px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-xl hover:bg-gray-100 transition-colors flex items-center gap-1.5 disabled:opacity-40"
    >
      <RefreshCw class="w-3.5 h-3.5" /> 刷新状态
    </button>
    <div class="flex items-center gap-2 min-w-0">
      <!-- 状态指示（不影响按钮显隐） -->
      <template v-if="statusKind === 'running'">
        <Loader2 class="w-4 h-4 text-blue-500 animate-spin shrink-0" />
        <span class="text-[12px] text-blue-600 font-medium">LLM 分析中</span>
        <span v-if="status?.phase" class="text-[11px] text-gray-400 truncate">{{ phaseLabel(status.phase) }}</span>
        <span v-if="status?.queue_depth != null && status.queue_depth > 0"
          class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-600 border border-amber-200 shrink-0"
          title="该会话有界队列当前积压跳数"
        >队列 {{ status.queue_depth }}</span>
      </template>
      <template v-else-if="statusKind === 'completed'">
        <CheckCircle2 class="w-4 h-4 text-emerald-500 shrink-0" />
        <span class="text-[12px] text-emerald-600 font-medium">分析完成</span>
      </template>
      <template v-else-if="statusKind === 'failed'">
        <XCircle class="w-4 h-4 text-red-500 shrink-0" />
        <span class="text-[12px] text-red-600 font-medium">分析失败</span>
        <span v-if="status?.reason" class="text-[11px] text-gray-400 truncate max-w-[200px]">{{ status.reason }}</span>
      </template>
      <template v-else-if="statusKind === 'pending'">
        <Clock class="w-4 h-4 text-amber-500 shrink-0" />
        <span class="text-[12px] text-amber-600 font-medium">有待分析行为</span>
      </template>
      <template v-else>
        <!-- uptodate / idle：空闲（逐跳改版后无待分析即空闲） -->
        <CheckCircle2 class="w-4 h-4 text-gray-400 shrink-0" />
        <span class="text-[12px] text-gray-500 font-medium">空闲</span>
      </template>
      <!-- 触发分析：仅横向（手动触发横轴确认）；纵向逐跳改版后 showTrigger=false 隐藏 -->
      <button v-if="showTrigger !== false" @click="$emit('trigger')" :disabled="triggerDisabled"
        class="px-3 py-1.5 text-[12px] font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:hover:bg-gray-300 shrink-0"
      >
        <Loader2 v-if="triggerLoading || polling" class="w-3.5 h-3.5 animate-spin" />
        <Zap v-else class="w-3.5 h-3.5" /> 触发分析
      </button>
    </div>
  </div>
</template>
