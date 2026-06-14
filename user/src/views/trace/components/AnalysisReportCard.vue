<script setup lang="ts">
/**
 * AnalysisReportCard — 单条分析报告卡片（纵向 / 横向共用）。
 *
 * 横向报告带 sessions_scanned 徽章；node_verdicts 中的可疑 DID 可点击，
 * 触发 view-dossier 事件供父视图跳转到恶意档案。
 */
import { verdictBadge, severityBadgeCls, formatTime, formatDid } from '../../../composables/useTraceFormat'
import type { AnalysisReport } from '../types'

defineProps<{ report: AnalysisReport; axis?: 'v' | 'h' }>()
const emit = defineEmits<{ (e: 'view-dossier', did: string): void }>()
</script>

<template>
  <div class="bg-white rounded-xl border border-gray-200 overflow-hidden hover:border-gray-300 transition-colors">
    <div class="p-4">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <span class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-purple-50 text-purple-600 border border-purple-200">
            Batch #{{ report.batch_index }}
          </span>
          <span class="text-[11px] text-gray-400 font-mono">
            trace {{ report.from_trace_id }} → {{ report.to_trace_id }}
          </span>
          <span v-if="report.sessions_scanned != null" class="px-1.5 py-0.5 rounded text-[9px] font-medium bg-blue-50 text-blue-600 border border-blue-200">
            {{ report.sessions_scanned }} sessions
          </span>
        </div>
        <span class="text-[10px] text-gray-400">{{ formatTime(report.timestamp) }}</span>
      </div>

      <div v-if="report.report?.overall_verdict" class="flex items-center gap-2 mb-3">
        <span class="text-[11px] text-gray-500">Verdict:</span>
        <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', verdictBadge(report.report.overall_verdict).cls]">
          {{ verdictBadge(report.report.overall_verdict).text }}
        </span>
      </div>

      <p v-if="report.report?.summary" class="text-[12px] text-gray-600 leading-relaxed mb-3">
        {{ report.report.summary }}
      </p>

      <div v-if="report.report?.node_verdicts?.length" class="space-y-2 mt-3">
        <div class="text-[11px] font-medium text-gray-400">节点裁决 ({{ report.report.node_verdicts.length }})</div>
        <div v-for="(nv, i) in report.report.node_verdicts" :key="i"
          class="flex items-center gap-2 p-2 bg-gray-50 rounded-lg border border-gray-100 text-[11px]"
        >
          <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-medium', severityBadgeCls(nv.severity || '')]">
            {{ nv.severity || '--' }}
          </span>
          <button
            v-if="nv.node_did"
            @click="emit('view-dossier', nv.node_did)"
            class="font-mono text-gray-600 truncate flex-1 text-left hover:text-indigo-600 hover:underline transition-colors"
            :title="`查看 ${nv.node_did} 的恶意档案`"
          >{{ formatDid(nv.node_did) }}</button>
          <span v-else class="text-gray-400">--</span>
          <span v-if="nv.taint_score != null" class="text-gray-400">taint: {{ nv.taint_score }}</span>
        </div>
      </div>

      <details class="mt-3">
        <summary class="text-[11px] text-gray-400 cursor-pointer hover:text-gray-600 transition-colors">查看原始报告</summary>
        <div class="mt-2 bg-gray-50 rounded-lg p-3 text-[11px] font-mono text-gray-600 whitespace-pre-wrap overflow-x-auto max-h-[300px] overflow-y-auto">
          {{ JSON.stringify(report.report, null, 2) }}
        </div>
      </details>
    </div>
  </div>
</template>
