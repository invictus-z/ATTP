<script setup lang="ts">
/**
 * AnalysisReportCard — 单条横轴确认报告卡片。
 *
 * 渲染横轴 report blob：confirmed / overall_verdict / triggered_by / summary
 * + 单个 verdict（severity / taint_score / threat_pattern / evidence / evidence_items）
 * + selected_sessions（复核会话）。verdict.did 可点击触发 view-dossier 跳转恶意档案。
 *
 * 注：逐跳改版后报告 blob 不再有 node_verdicts，改为单个 verdict 对象。
 */
import { verdictBadge, severityBadgeCls, formatTime, formatDid } from '../../../composables/useTraceFormat'
import type { AnalysisReport } from '../types'

defineProps<{ report: AnalysisReport; axis?: 'v' | 'h' }>()
const emit = defineEmits<{ (e: 'view-dossier', did: string): void }>()
</script>

<template>
  <div class="bg-white rounded-xl border border-gray-200 overflow-hidden hover:border-gray-300 transition-colors">
    <div class="p-4">
      <!-- 头部 -->
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

      <!-- confirmed + overall_verdict + triggered_by -->
      <div class="flex items-center gap-2 mb-3 flex-wrap">
        <span v-if="report.report?.confirmed"
          class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-red-50 text-red-600 border border-red-200">确认恶意</span>
        <span v-else
          class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-emerald-50 text-emerald-600 border border-emerald-200">判为良性</span>
        <span v-if="report.report?.overall_verdict"
          :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', verdictBadge(report.report.overall_verdict).cls]">
          {{ verdictBadge(report.report.overall_verdict).text }}
        </span>
        <span v-if="report.report?.triggered_by"
          class="px-1.5 py-0.5 rounded text-[9px] font-medium bg-gray-100 text-gray-500 border border-gray-200">
          {{ report.report.triggered_by === 'manual' ? '手动触发' : 'F 阈值触发' }}
        </span>
      </div>

      <!-- summary -->
      <p v-if="report.report?.summary" class="text-[12px] text-gray-600 leading-relaxed mb-3">
        {{ report.report.summary }}
      </p>

      <!-- 单个 verdict（替代旧 node_verdicts 列表） -->
      <div v-if="report.report?.verdict" class="space-y-2 mt-3">
        <div class="text-[11px] font-medium text-gray-400">节点裁决</div>
        <div class="p-2 bg-gray-50 rounded-lg border border-gray-100 text-[11px]">
          <div class="flex items-center gap-2 mb-1.5 flex-wrap">
            <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-medium', severityBadgeCls(report.report.verdict.severity || '')]">
              {{ report.report.verdict.severity || '--' }}
            </span>
            <button v-if="report.report.verdict.did"
              @click="emit('view-dossier', report.report.verdict.did)"
              class="font-mono text-gray-600 truncate hover:text-indigo-600 hover:underline transition-colors text-left"
              :title="`查看 ${report.report.verdict.did} 的恶意档案`"
            >{{ formatDid(report.report.verdict.did) }}</button>
            <span v-if="report.report.verdict.taint_score != null" class="text-gray-400 ml-auto">
              taint: <span class="font-mono text-gray-600">{{ report.report.verdict.taint_score }}</span>
            </span>
          </div>
          <p v-if="report.report.verdict.threat_pattern && report.report.verdict.threat_pattern !== 'none'" class="text-gray-500 mb-1">
            <span class="text-gray-400">模式：</span>{{ report.report.verdict.threat_pattern }}
          </p>
          <p v-if="report.report.verdict.evidence" class="text-gray-500">{{ report.report.verdict.evidence }}</p>
          <!-- evidence_items -->
          <div v-if="report.report.verdict.evidence_items?.length" class="mt-1.5 pt-1.5 border-t border-gray-200 space-y-1">
            <div v-for="(e, i) in report.report.verdict.evidence_items" :key="i" class="text-gray-500 flex items-start gap-1.5">
              <span class="text-gray-400 shrink-0">·</span>
              <span>{{ e.description }}</span>
              <span v-if="e.trace_ids?.length" class="text-[10px] text-gray-400 font-mono shrink-0 ml-auto">trace {{ e.trace_ids.join(',') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- selected_sessions（复核会话） -->
      <div v-if="report.report?.selected_sessions?.length" class="mt-2 flex items-center gap-1 flex-wrap">
        <span class="text-[10px] text-gray-400">复核会话：</span>
        <span v-for="(s, i) in report.report.selected_sessions.slice(0, 8)" :key="i"
          class="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 font-mono text-[10px] border border-gray-200 truncate max-w-[160px]"
          :title="s"
        >{{ s }}</span>
        <span v-if="report.report.selected_sessions.length > 8" class="text-[10px] text-gray-400">+{{ report.report.selected_sessions.length - 8 }}</span>
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
